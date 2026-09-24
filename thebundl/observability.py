"""Credential-safe terminal events and append-only local error records."""
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import json
import sys

ERROR_LOG = Path(__file__).resolve().parent.parent / 'pipeline-errors.txt'


def progress(message: str) -> None:
    print(f'[{datetime.now(UTC):%H:%M:%S} UTC] {message}', file=sys.stderr, flush=True)


def record_error(stage: str, error_type: str, description: str) -> None:
    # Callers supply fixed descriptions, never raw exception bodies or page text.
    entry = dict(date=datetime.now(UTC).isoformat(), stage=stage,
                 error_type=error_type, description=description)
    try:
        with ERROR_LOG.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')
    except OSError:
        progress('Could not write pipeline-errors.txt; check root directory permissions.')
    progress(f'{stage}: {error_type}; {description}')


@contextmanager
def request_event(service: str):
    progress(f'{service}: request started')
    try:
        yield
    except Exception as error:
        record_error(service, type(error).__name__, 'Request failed; check credentials, service availability and request limits.')
        raise
    else:
        progress(f'{service}: response received')
