"""Common utilities for running Claude CLI."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


def run_claude_cli(prompt_file: Path, claude_command: str, claude_args: List[str], log_file: Path) -> Dict[str, Any]:
    """Run Claude CLI with the given prompt file.
    
    Args:
        prompt_file: Path to the prompt file
        claude_command: Claude command to run (e.g., 'claude')
        claude_args: List of arguments to pass to Claude
        log_file: Path to save the session log
        
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
    
    # Construct command (without the prompt file as argument)
    cmd = [claude_command] + claude_args
    
    try:
        # Run Claude with the prompt as stdin
        result = subprocess.run(
            cmd,
            input=prompt_content,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        # Save session log
        session_log = {
            "timestamp": datetime.now().isoformat(),
            "command": " ".join(cmd),
            "prompt_file": str(prompt_file),
            "prompt_method": "stdin",
            "return_code": result.returncode,
            "stdout": result.stdout,
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
                "log_file": log_file
            }
        
        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "log_file": log_file
        }
        
    except subprocess.TimeoutExpired:
        # Save what we can to the log file
        session_log = {
            "timestamp": datetime.now().isoformat(),
            "command": " ".join(cmd),
            "prompt_file": str(prompt_file),
            "prompt_method": "stdin",
            "error": "Process timed out after 300 seconds"
        }
        log_file.write_text(json.dumps(session_log, indent=2))
        
        return {
            "success": False,
            "error": "Claude CLI timed out after 5 minutes",
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