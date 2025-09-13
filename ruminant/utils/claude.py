"""Common utilities for running Claude CLI."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


def run_claude_cli(prompt_file: Path, claude_command: str, claude_args: List[str], log_file: Path) -> Dict[str, Any]:
    """Run Claude CLI with the given prompt file using streaming JSON output.
    
    Args:
        prompt_file: Path to the prompt file
        claude_command: Claude command to run (e.g., 'claude')
        claude_args: List of arguments to pass to Claude
        log_file: Path to save the session log including streaming output
        
    Returns:
        Dictionary with success status, stdout, stderr, and log_file
    """
    # Read the prompt content
    try:
        prompt_content = prompt_file.read_text()
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read prompt file: {e}",
            "log_file": log_file
        }
    
    # Ensure we have the required flags for non-interactive mode with streaming JSON
    # Note: --verbose is required when using --print with --output-format stream-json
    required_args = ["--print", "--output-format", "stream-json", "--verbose"]
    
    # Build the final command arguments
    final_args = []
    has_print = False
    has_output_format = False
    has_verbose = False
    
    # Check existing args to avoid duplicates
    i = 0
    while i < len(claude_args):
        arg = claude_args[i]
        if arg == "--print" or arg == "-p":
            has_print = True
            final_args.append(arg)
        elif arg == "--output-format":
            has_output_format = True
            # Skip this and the next argument (the format value)
            if i + 1 < len(claude_args):
                i += 1  # Skip the format value
        elif arg == "--verbose":
            has_verbose = True
            final_args.append(arg)
        else:
            final_args.append(arg)
        i += 1
    
    # Add required flags if not present
    if not has_print:
        final_args.insert(0, "--print")
    if not has_output_format:
        final_args.extend(["--output-format", "stream-json"])
    if not has_verbose:
        final_args.append("--verbose")
    
    # Construct command
    cmd = [claude_command] + final_args
    
    try:
        # Run Claude with the prompt as stdin
        result = subprocess.run(
            cmd,
            input=prompt_content,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        # Parse streaming JSON output to extract meaningful content
        streaming_output = []
        final_content = ""
        
        # Each line in stdout should be a JSON object when using stream-json
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    json_obj = json.loads(line)
                    streaming_output.append(json_obj)
                    
                    # Extract content from different event types
                    if json_obj.get("type") == "content" and "text" in json_obj:
                        final_content += json_obj["text"]
                    elif json_obj.get("type") == "text" and "text" in json_obj:
                        final_content += json_obj["text"]
                        
                except json.JSONDecodeError:
                    # Some lines might not be JSON (e.g., error messages)
                    pass
        
        # Save comprehensive session log
        session_log = {
            "timestamp": datetime.now().isoformat(),
            "command": " ".join(cmd),
            "prompt_file": str(prompt_file),
            "prompt_method": "stdin",
            "output_format": "stream-json",
            "return_code": result.returncode,
            "streaming_events": streaming_output,
            "extracted_content": final_content,
            "raw_stdout": result.stdout,
            "stderr": result.stderr
        }
        
        # Write session log to file
        log_file.write_text(json.dumps(session_log, indent=2))
        
        # Check if Claude ran successfully
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Claude CLI failed",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "streaming_output": streaming_output,
                "log_file": log_file
            }
        
        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "streaming_output": streaming_output,
            "extracted_content": final_content,
            "log_file": log_file
        }
        
    except subprocess.TimeoutExpired:
        # Save what we can to the log file
        session_log = {
            "timestamp": datetime.now().isoformat(),
            "command": " ".join(cmd),
            "prompt_file": str(prompt_file),
            "prompt_method": "stdin",
            "output_format": "stream-json",
            "error": "Process timed out after 600 seconds"
        }
        log_file.write_text(json.dumps(session_log, indent=2))
        
        return {
            "success": False,
            "error": "Claude CLI timed out after 10 minutes",
            "timeout": True,
            "log_file": log_file
        }
    
    except Exception as e:
        # Save error to log file
        session_log = {
            "timestamp": datetime.now().isoformat(),
            "command": " ".join(cmd),
            "prompt_file": str(prompt_file),
            "prompt_method": "stdin",
            "output_format": "stream-json",
            "error": str(e)
        }
        log_file.write_text(json.dumps(session_log, indent=2))
        
        return {
            "success": False,
            "error": str(e),
            "log_file": log_file
        }


def validate_summary_file(summary_file: Path) -> bool:
    """Validate that a summary file contains valid JSON and not stream logs.
    
    Args:
        summary_file: Path to the summary file to validate
        
    Returns:
        True if the file is valid, False otherwise
    """
    if not summary_file.exists():
        return False
    
    try:
        with open(summary_file) as f:
            content = f.read()
            
            # Check if it's stream-json logs (Claude CLI output)
            if "stream-json" in content or "MessageStream" in content:
                return False
            
            # Try to parse as JSON
            data = json.loads(content)
            
            # Check for required fields based on file type
            # Group summaries have 'group' field, individual summaries have 'repo' field
            if "group" in data:
                required_fields = ["week", "year", "group"]
            else:
                required_fields = ["week", "year", "repo"]
            
            return all(field in data for field in required_fields)
            
    except json.JSONDecodeError:
        return False
    except Exception:
        return False