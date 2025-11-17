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
        help='Set dry air flow rate (L/min)'
    )

    parser.add_argument(
        '--wet-flow',
        type=float,
        help='Set wet air flow rate (L/min)'
    )

    # Automated experiment arguments
    parser.add_argument(
        '--experiment',
        action='store_true',
        help='Run automated humidity ramp experiment'
    )
    
    parser.add_argument(
        '--direction',
        type=str,
        choices=['up', 'down'],
        default='up',
        help='Experiment direction: "up" for 0%% to 100%% RH, "down" for 100%% to 0%% RH (default: up)'
    )
    
    parser.add_argument(
        '--steps',
        type=int,
        default=10,
        help='Number of steps between start and end RH (default: 10)'
    )
    
    parser.add_argument(
        '--duration',
        type=float,
        default=60.0,
        help='Total experiment duration in minutes (default: 60.0)'
    )
    
    parser.add_argument(
        '--max-flow',
        type=float,
        default=2.0,
        help='Maximum/target total flow rate (dry + wet) in L/min. System will aim for this but may go below if needed for RH control (default: 2.0)'
    )
    
    parser.add_argument(
        '--control-interval',
        type=float,
        default=5.0,
        help='Time between control updates in seconds (default: 5.0)'
    )
    
    parser.add_argument(
        '--rh-tolerance',
        type=float,
        default=10.0,
        help='Maximum allowed deviation from target RH before adjustment in %% (default: 10.0)'
    )

    return parser.parse_args(argv)
