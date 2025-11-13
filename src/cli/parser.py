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
    
    parser.add_argument(
        '--interval',
        type=float,
        default=1.0,
        help='Sampling interval in seconds (default: 1.0)'
    )

    parser.add_argument(
        '--dry-flow',
        type=float,
        help='Set dry air flow rate (ml/min)'
    )

    parser.add_argument(
        '--wet-flow',
        type=float,
        help='Set wet air flow rate (ml/min)'
    )

    return parser.parse_args(argv)
