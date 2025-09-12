"""Batch generate weekly summaries in chronological order."""

import typer
from typing import Optional, List
from datetime import datetime, timedelta

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list
from ..utils.paths import get_data_dir
from ..utils.logging import console, success, error, warning, info, step
from .summarize_week import summarize_week_main


def summarize_weeks_batch_main(
    weeks: int = 1,
    year: Optional[int] = None,
    week: Optional[int] = None,
    claude_args: Optional[str] = None,
    dry_run: bool = False,
    skip_existing: bool = True,
    lookback_weeks: int = 3
) -> None:
    """
    Generate weekly summaries for multiple weeks in chronological order.
    
    This ensures that each week summary can reference the already-generated
    summaries from previous weeks, building context progressively.
    """
    
    try:
        config = load_config()
        
        # Determine target week (the most recent week to summarize)
        if year and week:
            target_year, target_week = year, week
        else:
            target_year, target_week = get_last_complete_week()
        
        # Get list of weeks to summarize (already in chronological order, oldest first)
        week_list = get_week_list(weeks, target_year, target_week)
        
        info(f"Generating weekly summaries for {len(week_list)} weeks in chronological order")
        
        successful = 0
        skipped = 0
        failed = 0
        
        for w_year, w_week in week_list:
            # Import the function from the main module
            from .summarize_week import get_week_summary_path
            week_summary_file = get_week_summary_path(w_year, w_week)
            
            # Check if summary already exists
            if skip_existing and week_summary_file.exists():
                info(f"Week {w_week}, {w_year}: Summary already exists, skipping")
                skipped += 1
                continue
            
            step(f"Generating summary for Week {w_week}, {w_year} ({successful + skipped + failed + 1}/{len(week_list)})")
            
            try:
                # Generate the week summary
                summarize_week_main(
                    year=w_year,
                    week=w_week,
                    claude_args=claude_args,
                    dry_run=dry_run,
                    prompt_only=False,
                    lookback_weeks=lookback_weeks
                )
                
                successful += 1
                success(f"Week {w_week}, {w_year}: Summary generated successfully")
                
            except Exception as e:
                failed += 1
                error(f"Week {w_week}, {w_year}: Failed to generate summary - {e}")
                
                # Optionally continue or stop on failure
                if not dry_run:
                    console.print("[yellow]Continue with remaining weeks? (y/n):[/yellow] ", end="")
                    response = input().strip().lower()
                    if response != 'y':
                        warning("Batch processing stopped by user")
                        break
        
        # Summary
        console.print("\n" + "=" * 50)
        console.print(f"✨ Batch Summary Generation Complete")
        console.print(f"  • Successful: {successful}")
        console.print(f"  • Skipped: {skipped}")
        console.print(f"  • Failed: {failed}")
        console.print("=" * 50)
        
        if failed > 0:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Batch processing interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Batch processing failed: {e}")
        raise typer.Exit(1)