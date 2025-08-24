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
from re_agent.exc import RateLimitExceeded, DataValidationError, NoCompsError, MissingFieldError
from re_agent.models import CsvRow


def main():
    parser = argparse.ArgumentParser(description="Zillow ARV CLI")
    parser.add_argument("--config", required=False, default='config.example.yaml', help="Path to YAML config")
    parser.add_argument("--out", default=None, help="Path to output CSV")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs")
    args = parser.parse_args()

    ensure_dirs()
    logger = setup_logging(verbose=args.verbose)

    try:
        cfg = load_config(args.config, logger=logger)
    except DataValidationError as e:
        logger.error(f"Config/LLM parsing failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
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
                search_res = client.search_properties(geo=geo, page=page, cfg=cfg)

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

                    details = client.get_property_details(zpid)
                    comps_payload = client.get_property_comps(zpid=zpid, subject=details, cfg=cfg)

                    row, _ = estimate_arv_and_profit(subject=details or p, comps_payload=comps_payload, cfg=cfg)

                    def pick(*vals):
                        for v in vals:
                            if v is not None and v != "":
                                return v
                        return None

                    row.update({
                        "zpid": zpid,
                        "address": pick(details.get("address"), p.get("address")),
                        "city": pick(details.get("city"), p.get("city")),
                        "state": pick(details.get("state"), p.get("state")),
                        "zip": pick(details.get("zipcode"), details.get("zip"), p.get("zipcode"), p.get("zip")),
                        "latitude": pick(details.get("latitude"), p.get("latitude")),
                        "longitude": pick(details.get("longitude"), p.get("longitude")),
                        "url": pick(details.get("url"), p.get("detailUrl"), p.get("url")),
                        "status": pick(details.get("homeStatus"), p.get("status")),
                        "dom": pick(details.get("daysOnZillow"), p.get("dom"), p.get("daysOnZillow")),
                        "hoa": pick(details.get("hoaFee"), p.get("hoa")),
                        "list_price": pick(details.get("price"), p.get("price"), p.get("listPrice")),
                        "beds": pick(details.get("bedrooms"), p.get("beds")),
                        "baths": pick(details.get("bathrooms"), p.get("baths")),
                        "sqft": pick(details.get("livingArea"), p.get("sqft"), p.get("livingArea")),
                        "lot_sqft": pick(details.get("lotAreaValue"), p.get("lotSize"), p.get("lotAreaValue")),
                        "year_built": pick(details.get("yearBuilt"), p.get("yearBuilt")),
                        "home_type": pick(details.get("homeType"), p.get("homeType")),
                        "comp_radius_mi": cfg.arv_config.comp_radius_mi,
                        "comp_window_months": cfg.arv_config.comp_window_months,
                        "search_geo": geo,
                        "page": page,
                        "ts_utc": ts_utc,
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

                    # Validate CSV row strictly against schema
                    csv_model = CsvRow.model_validate(row)
                    writer.writerow(csv_model.model_dump())
                    total_rows += 1

    logger.info(f"Wrote {total_rows} rows → {out_path}")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RateLimitExceeded as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except (NoCompsError, MissingFieldError, DataValidationError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Fail-fast on unexpected exceptions
        print(f"Unhandled error: {e}", file=sys.stderr)
        sys.exit(1)
