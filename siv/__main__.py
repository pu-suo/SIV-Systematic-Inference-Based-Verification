"""
SIV: Systematic Inference-Based Verification for NL-to-FOL Translation

Usage:
    python -m siv inspect  "sentence" [--candidate FOL] [--extraction-json JSON]
    python -m siv score    input.json [--format {human,json}]
    python -m siv generate input.json [--compare-to-gold NAME]
    python -m siv setup

Run 'python -m siv <command> --help' for command-specific options.
"""
import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        raise SystemExit(0)

    command = sys.argv[1]
    # Remove the subcommand from argv so argparse in each script sees
    # only its own arguments.
    sys.argv = [f"python -m siv {command}"] + sys.argv[2:]

    if command == "inspect":
        from scripts.siv_inspect import main as cmd_main
        cmd_main()
    elif command == "score":
        from scripts.siv_score import main as cmd_main
        cmd_main()
    elif command == "generate":
        from scripts.siv_generate import main as cmd_main
        cmd_main()
    elif command == "setup":
        _run_setup()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Available commands: inspect, score, generate, setup", file=sys.stderr)
        raise SystemExit(2)


def _run_setup():
    """Run the setup script from Python (for platforms without bash)."""
    import subprocess
    import os
    setup_script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup.sh")
    if os.path.exists(setup_script):
        raise SystemExit(subprocess.call(["bash", setup_script]))
    else:
        print("Setup script not found. Run: bash scripts/setup.sh", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
