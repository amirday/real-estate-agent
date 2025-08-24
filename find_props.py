#!/usr/bin/env python3
import argparse
import csv
import os
import sys
from datetime import datetime, timezone

from re_agent.config import load_config
from re_agent.logging_util import setup_logging
from re_agent.api import ZillowClient
from re_agent.arv import estimate_arv_and_profit
from re_agent.csv_out import ensure_dirs


def main():
    parser = argparse.ArgumentParser(description="Zillow ARV CLI")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--out", default=None, help="Path to output CSV")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs")
    args = parser.parse_args()

    ensure_dirs()
    logger = setup_logging(verbose=args.verbose)

    try:
        cfg = load_config(args.config, logger=logger)
    except Exception as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Log merged config at DEBUG
    logger.debug(f"Merged config: {cfg.model_dump_json(indent=2)}")

    client = ZillowClient(logger=logger)

    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_path = args.out or os.path.join("out", f"properties_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    fieldnames = [
        # Identification
        "zpid", "address", "city", "state", "zip", "latitude", "longitude", "url",
        "status", "dom", "hoa",
        # Specs
        "list_price", "beds", "baths", "sqft", "lot_sqft", "year_built", "home_type",
        # ARV
        "arv_estimate", "arv_ppsf", "comp_count", "comp_radius_mi", "comp_window_months", "arv_confidence",
        # Deal
        "list_to_arv_pct",
        # Profit
        "profit_conservative", "profit_median", "profit_optimistic",
        # Ops
        "search_geo", "page", "ts_utc",
        # Optional: reason if missing
        "note",
    ]

    wrote_header = False
    total_rows = 0

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        wrote_header = True

        for geo in cfg.filters.geos:
            logger.info(f"Searching: {geo}")
            for page in range(1, (cfg.filters.page_cap or 1) + 1):
                try:
                    search_res = client.search_properties(geo=geo, page=page, cfg=cfg)
                except Exception as e:
                    logger.error(f"Search failed for {geo} page {page}: {e}")
                    break

                props = search_res.get("results") or search_res.get("props") or []
                logger.info(f"Found {len(props)} properties for geo={geo} page={page}")
                if not props:
                    # Stop paginating if none
                    break

                for p in props:
                    zpid = str(p.get("zpid") or p.get("zpid_str") or p.get("id") or "")
                    if not zpid:
                        logger.debug("Skipping result without zpid")
                        continue

                    try:
                        details = client.get_property_details(zpid)
                    except Exception as e:
                        logger.warning(f"Details failed for zpid={zpid}: {e}")
                        details = {}

                    try:
                        comps_payload = client.get_property_comps(zpid=zpid, subject=details, cfg=cfg)
                    except Exception as e:
                        logger.warning(f"Comps failed for zpid={zpid}: {e}")
                        comps_payload = {"comps": []}

                    row, note = estimate_arv_and_profit(subject=details or p, comps_payload=comps_payload, cfg=cfg)

                    row.update({
                        "zpid": zpid,
                        "address": details.get("address") or p.get("address") or "",
                        "city": details.get("city") or p.get("city") or "",
                        "state": details.get("state") or p.get("state") or "",
                        "zip": details.get("zipcode") or details.get("zip") or p.get("zipcode") or p.get("zip") or "",
                        "latitude": details.get("latitude") or p.get("latitude") or "",
                        "longitude": details.get("longitude") or p.get("longitude") or "",
                        "url": details.get("url") or p.get("detailUrl") or p.get("url") or "",
                        "status": details.get("homeStatus") or p.get("status") or "",
                        "dom": details.get("daysOnZillow") or p.get("dom") or p.get("daysOnZillow") or "",
                        "hoa": details.get("hoaFee") or p.get("hoa") or "",
                        "list_price": details.get("price") or p.get("price") or p.get("listPrice") or "",
                        "beds": details.get("bedrooms") or p.get("beds") or "",
                        "baths": details.get("bathrooms") or p.get("baths") or "",
                        "sqft": details.get("livingArea") or p.get("sqft") or p.get("livingArea") or "",
                        "lot_sqft": details.get("lotAreaValue") or p.get("lotSize") or p.get("lotAreaValue") or "",
                        "year_built": details.get("yearBuilt") or p.get("yearBuilt") or "",
                        "home_type": details.get("homeType") or p.get("homeType") or "",
                        "comp_radius_mi": cfg.arv_config.comp_radius_mi,
                        "comp_window_months": cfg.arv_config.comp_window_months,
                        "search_geo": geo,
                        "page": page,
                        "ts_utc": ts_utc,
                        "note": note or "",
                    })

                    # Deal screen filter
                    if cfg.deal_screen and cfg.deal_screen.max_list_to_arv_pct is not None:
                        lta = row.get("list_to_arv_pct")
                        if lta is not None and lta != "":
                            try:
                                if float(lta) > float(cfg.deal_screen.max_list_to_arv_pct):
                                    logger.debug(f"Filtered out by deal screen zpid={zpid} LTA={lta}")
                                    continue
                            except Exception:
                                pass

                    writer.writerow(row)
                    total_rows += 1

    logger.info(f"Wrote {total_rows} rows → {out_path}")


if __name__ == "__main__":
    main()

