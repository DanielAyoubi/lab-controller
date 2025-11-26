from __future__ import annotations

import argparse
from typing import Optional


def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='N-SIM Microscope Environmental Control System'
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config.py',
        help='Path to configuration file (default: config.py)'
    )
    
    # Manual flow control
    parser.add_argument(
        '--dry-flow',
        type=float,
        help='Set dry air flow rate (L/min)'
    )

    parser.add_argument(
        '--wet-flow',
        type=float,
        help='Set wet air flow rate (L/min)'
    )

    # Experiment mode
    parser.add_argument(
        '--experiment',
        action='store_true',
        help='Run automated humidity ramp experiment (configure details in config file)'
    )

    return parser.parse_args(argv)
