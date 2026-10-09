"""Idempotent schema v1 bootstrap. Future versions must add explicit migrations."""
import os
from .storage import Store

def main():
    store = Store(os.environ.get('DATABASE_URL', 'sqlite:///./finagent.db'))
    print('Application schema version 1 ready (' + store.engine.dialect.name + ')')

if __name__ == '__main__':
    main()
