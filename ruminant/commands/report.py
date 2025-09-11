"""End-to-end report generation command."""

import typer
from typing import Optional, List

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list
from ..utils.paths import (
    parse_repo,
    get_cache_file_path,
    get_prompt_file_path,
    get_summary_file_path,
)
from ..utils.logging import (
    success,
    error,
    warning,
    info,
    step,
    print_repo_list,
    confirm_operation,
)
from .sync import sync_main
from .summarize import summarize_main


def should_skip_sync(
    repositories: List[str], year: int, week: int, skip_existing: bool
) -> bool:
    """Check if sync step should be skipped."""
    if not skip_existing:
        return False

    # Check if all repos have cache files
    for repo in repositories:
        cache_file = get_cache_file_path(repo, year, week)
        if not cache_file.exists():
            return False
    return True


def should_skip_summarize(
    repositories: List[str], year: int, week: int, skip_existing: bool
) -> bool:
    """Check if summarize step should be skipped."""
    if not skip_existing:
        return False

    # Check if all repos have summary files
    for repo in repositories:
        summary_file = get_summary_file_path(repo, year, week)
        if not summary_file.exists():
            return False
    return True


def report_main(
    repos: Optional[List[str]] = typer.Argument(
        None, help="Repository names (owner/repo format)"
    ),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to process"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force_sync: bool = typer.Option(
        False, "--force-sync", help="Force refresh GitHub data cache"
    ),
    claude_args: Optional[str] = typer.Option(
        None, "--claude-args", help="Additional arguments for Claude CLI"
    ),
    skip_sync: bool = typer.Option(
        False, "--skip-sync", help="Skip the sync step (use existing cache)"
    ),
    skip_summarize: bool = typer.Option(
        False, "--skip-summarize", help="Skip the summarize step"
    ),
    skip_existing: bool = typer.Option(
        False, "--skip-existing", help="Skip weeks that already have reports"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without executing"
    ),
) -> None:
    """Run the complete end-to-end reporting workflow: sync → summarize."""

    try:
        config = load_config()

        # Determine repositories to process
        if repos:
            # Validate repo format
            for repo in repos:
                try:
                    parse_repo(repo)
                except ValueError as e:
                    error(str(e))
                    raise typer.Exit(1)
            repositories_to_process = repos
        else:
            repositories_to_process = config.repositories

        if not repositories_to_process:
            error(
                "No repositories specified. Use arguments or configure in .ruminant.toml"
            )
            raise typer.Exit(1)

        # Determine time range
        if year and week:
            target_year, target_week = year, week
        else:
            target_year, target_week = get_last_complete_week()

        # Get list of weeks to process
        if weeks > 1:
            week_list = get_week_list(weeks, target_year, target_week)
        else:
            week_list = [(target_year, target_week)]

        # Show what we'll be processing
        print_repo_list(repositories_to_process)

        if len(week_list) > 1:
            info(
                f"Processing {len(week_list)} weeks: {week_list[0]} to {week_list[-1]}"
            )
        elif len(week_list) == 1:
            info(f"Processing week {week_list[0][1]} of {week_list[0][0]}")
        else:
            # No weeks to process (all skipped)
            return

        # Show workflow steps
        step("End-to-end workflow:")
        steps_to_run = []
        if not skip_sync:
            steps_to_run.append("📥 Sync GitHub data")
        if not skip_summarize:
            steps_to_run.append("🤖 Generate summaries with Claude")

        for step_desc in steps_to_run:
            info(f"  {step_desc}")

        if dry_run:
            info("DRY RUN MODE - No actual work will be performed")
            return

        # Confirm before proceeding (unless it's a single week for a single repo)
        if len(repositories_to_process) > 1 or len(week_list) > 1:
            total_operations = (
                len(repositories_to_process) * len(week_list) * len(steps_to_run)
            )
            if not confirm_operation(
                f"This will perform {total_operations} operations. Continue?"
            ):
                info("Aborted by user")
                return

        overall_success = True

        # Process each week
        for week_idx, (process_year, process_week) in enumerate(week_list, 1):
            if len(week_list) > 1:
                step(
                    f"\nProcessing week {week_idx}/{len(week_list)}: Week {process_week} of {process_year}"
                )

            # Calculate total steps for this week
            total_steps = 0
            if not skip_sync:
                total_steps += 1
            if not skip_summarize:
                total_steps += 1

            current_step = 0

            # Step 1: Sync GitHub data
            if not skip_sync:
                current_step += 1

                if should_skip_sync(
                    repositories_to_process, process_year, process_week, skip_existing
                ):
                    step(
                        f"Step {current_step}/{total_steps}: Skipping GitHub data sync (already exists)"
                    )
                    success("✅ GitHub data sync skipped (already exists)")
                else:
                    step(f"Step {current_step}/{total_steps}: Syncing GitHub data...")
                    try:
                        sync_main(
                            repos=repositories_to_process
                            if repositories_to_process != config.repositories
                            else None,
                            weeks=1,
                            year=process_year,
                            week=process_week,
                            force=force_sync,
                        )
                        success("✅ GitHub data sync completed")

                    except typer.Exit as e:
                        if e.exit_code != 0:
                            error("❌ GitHub data sync failed")
                            overall_success = False
                            if len(week_list) > 1 and not confirm_operation(
                                "Continue with remaining weeks?"
                            ):
                                raise typer.Exit(1)
                    except Exception as e:
                        error(f"❌ GitHub data sync failed: {e}")
                        overall_success = False
                        if len(week_list) > 1 and not confirm_operation(
                            "Continue with remaining weeks?"
                        ):
                            raise typer.Exit(1)

            # Step 2: Generate summaries
            if not skip_summarize:
                current_step += 1

                if should_skip_summarize(
                    repositories_to_process, process_year, process_week, skip_existing
                ):
                    step(
                        f"Step {current_step}/{total_steps}: Skipping summary generation (already exists)"
                    )
                    success("✅ Summary generation skipped (already exists)")
                else:
                    step(
                        f"Step {current_step}/{total_steps}: Generating summaries with Claude..."
                    )
                    try:
                        summarize_main(
                            repos=repositories_to_process
                            if repositories_to_process != config.repositories
                            else None,
                            weeks=1,
                            year=process_year,
                            week=process_week,
                            claude_args=claude_args,
                            dry_run=dry_run,
                            parallel_workers=None,
                        )
                        success("✅ Summary generation completed")

                    except typer.Exit as e:
                        if e.exit_code != 0:
                            error("❌ Summary generation failed")
                            overall_success = False
                            if len(week_list) > 1 and not confirm_operation(
                                "Continue with remaining weeks?"
                            ):
                                raise typer.Exit(1)
                    except Exception as e:
                        error(f"❌ Summary generation failed: {e}")
                        overall_success = False
                        if len(week_list) > 1 and not confirm_operation(
                            "Continue with remaining weeks?"
                        ):
                            raise typer.Exit(1)

        # Final summary
        if overall_success:
            success("🎉 End-to-end report generation completed successfully!")
            info("\nGenerated reports can be found in:")
            info("  Individual: data/summaries/owner/repo/week-NN-YYYY.json")
            info("\nTo generate group summaries, run:")
            info("  ruminant group <group-name>")
        else:
            warning("⚠️  Report generation completed with some errors")
            info("Check the logs above for details on what failed")

        if not overall_success:
            raise typer.Exit(1)

    except KeyboardInterrupt:
        warning("Report generation interrupted by user")
        raise typer.Exit(1)
    except typer.Exit:
        # Re-raise typer exits
        raise
    except Exception as e:
        error(f"Report generation failed: {e}")
        raise typer.Exit(1)