#!/usr/bin/env python3
"""Apply the documented v4 local patch to locked SACAD 2.8.3 source."""
from __future__ import annotations

import sys
from pathlib import Path

target = Path(sys.argv[1])
text = target.read_text(encoding="utf-8")
argument_anchor = '''    sacad.setup_common_args(arg_parser)
'''
argument = '''    arg_parser.add_argument(
        "--max-concurrent",
        type=int,
        default=int(os.environ.get("SACAD_MAX_CONCURRENT", "2")),
        help="Maximum simultaneous cover requests",
    )
'''
old_chunk = '        work_chunk_length = 4 if sys.platform.startswith("win") else 12\n'
new_chunk = '        work_chunk_length = max(1, args.max_concurrent)\n'
if text.count(argument_anchor) != 1 or text.count(old_chunk) != 1:
    raise SystemExit("SACAD source no longer matches the locked v4 patch target")
text = text.replace(argument_anchor, argument + argument_anchor).replace(old_chunk, new_chunk)
target.write_text(text, encoding="utf-8")
