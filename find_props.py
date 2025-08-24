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


def _pick_first_valid(*vals):
    """Helper to pick the first non-None, non-empty value."""
    for v in vals:
        if v is not None and v != "":
            return v
    return None


def _create_csv_row_from_property_data(zpid: str, details, search_result, 
                                       arv_data: dict, cfg, geo: str, page: int, ts_utc: str) -> CsvRow:
    """Create a CsvRow from property data following agents.md specification."""
    return CsvRow(
        # Identification fields (exact order from agents.md)
        zpid=zpid,
        address=_pick_first_valid(details.address, search_result.address),
        city=_pick_first_valid(details.city, search_result.city),
        state=_pick_first_valid(details.state, search_result.state),
        zip=_pick_first_valid(details.zipcode, search_result.zipcode),
        latitude=_pick_first_valid(details.latitude, search_result.latitude),
        longitude=_pick_first_valid(details.longitude, search_result.longitude),
        url=_pick_first_valid(details.url, search_result.detailUrl),
        status=_pick_first_valid(details.homeStatus, search_result.homeStatus),
        dom=_pick_first_valid(details.daysOnZillow, search_result.daysOnZillow),
        hoa=_pick_first_valid(details.hoaFee, None),  # search result doesn't have HOA
        # Specs
        list_price=_pick_first_valid(details.price, search_result.price),
        beds=_pick_first_valid(details.bedrooms, search_result.beds),
        baths=_pick_first_valid(details.bathrooms, search_result.baths),
        sqft=_pick_first_valid(details.livingArea, search_result.sqft),
        lot_sqft=_pick_first_valid(details.lotAreaValue, search_result.lotSize),
        year_built=_pick_first_valid(details.yearBuilt, search_result.yearBuilt),
        home_type=_pick_first_valid(details.homeType, search_result.homeType),
        # ARV data
        arv_estimate=arv_data["arv_estimate"],
        arv_ppsf=arv_data["arv_ppsf"],
        comp_count=arv_data["comp_count"],
        arv_confidence=arv_data["arv_confidence"],
        list_to_arv_pct=arv_data["list_to_arv_pct"],
        # Profit scenarios (nullable)
        profit_conservative=arv_data.get("profit_conservative"),
        profit_median=arv_data.get("profit_median"),
        profit_optimistic=arv_data.get("profit_optimistic"),
        # Config-driven fields
        comp_radius_mi=cfg.arv_config.comp_radius_mi,
        comp_window_months=cfg.arv_config.comp_window_months,
        # Operational fields
        search_geo=geo,
        page=page,
        ts_utc=ts_utc,
    )


def _should_filter_by_deal_screen(csv_row: CsvRow, deal_screen) -> bool:
    """Check if property should be filtered out by deal screening criteria."""
    if not deal_screen or deal_screen.max_list_to_arv_pct is None:
        return False
    
    if csv_row.list_to_arv_pct is None:
        return False
        
    try:
        return float(csv_row.list_to_arv_pct) > float(deal_screen.max_list_to_arv_pct)
    except (ValueError, TypeError):
        return False


def _process_single_property(zpid: str, search_result, client, cfg, geo: str, page: int, ts_utc: str, logger) -> CsvRow:
    """Process a single property through the full pipeline."""
    if not zpid:
        raise DataValidationError("Property missing zpid")
    
    # Get detailed property information
    details = client.get_property_details(zpid, cfg=cfg)
    if not details:
        raise DataValidationError(f"Failed to get property details for zpid={zpid}")
    
    # Get comps for ARV estimation
    comps_payload = client.get_property_comps(zpid=zpid, subject=details, cfg=cfg)
    
    # Compute ARV and profit scenarios - convert Pydantic models to dict for legacy compatibility
    subject_dict = details.model_dump() if hasattr(details, 'model_dump') else details
    comps_dict = comps_payload.model_dump() if hasattr(comps_payload, 'model_dump') else comps_payload
    arv_data, _ = estimate_arv_and_profit(subject=subject_dict, 
                                         comps_payload=comps_dict, cfg=cfg)
    
    # Create structured CSV row
    csv_row = _create_csv_row_from_property_data(
        zpid=zpid, 
        details=details, 
        search_result=search_result,
        arv_data=arv_data, 
        cfg=cfg, 
        geo=geo, 
        page=page, 
        ts_utc=ts_utc
    )
    
    # Apply deal screening filter
    if _should_filter_by_deal_screen(csv_row, cfg.deal_screen):
        logger.debug(f"Filtered out by deal screen zpid={zpid} LTA={csv_row.list_to_arv_pct}")
        return None
    
    return csv_row


def main():
    """Main CLI entry point following agents.md workflow."""
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Zillow ARV CLI")
    parser.add_argument("--config", required=False, default='config.example.yaml', 
                       help="Path to YAML config")
    parser.add_argument("--out", default=None, help="Path to output CSV")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument("--clear-cache", action="store_true", 
                            help="Clear all cache before run (overrides config setting)")
    cache_group.add_argument("--clear-llm-cache", action="store_true",
                            help="Clear only LLM cache before run (overrides config setting)")
    cache_group.add_argument("--clear-api-cache", action="store_true", 
                            help="Clear only API cache before run (overrides config setting)")
    args = parser.parse_args()

    # Setup infrastructure
    ensure_dirs()
    logger = setup_logging(verbose=args.verbose)

    try:
        # Handle CLI cache clearing overrides
        if args.clear_cache:
            from re_agent.cache import clear_all_cache
            logger.info("Clearing all cache via CLI argument")
            clear_all_cache()
            logger.debug("All cache cleared successfully")
        elif args.clear_llm_cache:
            from re_agent.cache import clear_llm_cache
            logger.info("Clearing LLM cache via CLI argument")
            clear_llm_cache()
            logger.debug("LLM cache cleared successfully")
        elif args.clear_api_cache:
            from re_agent.cache import clear_api_cache
            logger.info("Clearing API cache via CLI argument")
            clear_api_cache()
            logger.debug("API cache cleared successfully")

        # Load and validate configuration
        cfg = load_config(args.config, logger=logger)
        logger.debug(f"Merged config: {cfg.model_dump_json(indent=2)}")

        # Initialize Zillow API client
        client = ZillowClient(logger=logger)

        # Setup output
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out_path = args.out or os.path.join("out", f"properties_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        fieldnames = list(CsvRow.model_fields.keys())
        total_rows = 0

        # Process properties and write to CSV
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            # Search each geographic area
            for geo in cfg.filters.geos:
                logger.info(f"Searching: {geo}")
                
                # Paginate through results
                for page in range(1, (cfg.filters.page_cap or 1) + 1):
                    search_res = client.search_properties(geo=geo, page=page, cfg=cfg)
                    props = search_res.results or []
                    
                    logger.info(f"Found {len(props)} properties for geo={geo} page={page}")
                    if not props:
                        break  # Stop paginating if no results

                    # Process each property
                    for search_result in props:
                        zpid = search_result.zpid
                        if not zpid:
                            logger.debug("Skipping result without zpid")
                            continue

                        try:
                            csv_row = _process_single_property(
                                zpid=zpid,
                                search_result=search_result,
                                client=client,
                                cfg=cfg,
                                geo=geo,
                                page=page,
                                ts_utc=ts_utc,
                                logger=logger
                            )
                            
                            if csv_row:  # Not filtered out
                                writer.writerow(csv_row.model_dump())
                                total_rows += 1
                                
                        except Exception as e:
                            logger.error(f"Failed to process property zpid={zpid}: {e}")
                            raise  # Fail-fast as per agents.md

        logger.info(f"Wrote {total_rows} rows → {out_path}")
        return 0
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise  # Fail-fast principle


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
