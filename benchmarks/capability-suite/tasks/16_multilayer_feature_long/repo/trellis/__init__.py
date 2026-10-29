"""trellis: a small project and issue tracker.

Python 3.12, standard library only.  The package is layered:

    models / validation / dates     plain data and rules about it
    storage                         one Repository interface, two backends
                                    (SQLite and a JSON file), plus their
                                    schema-migration chains
    query                           the --where search language
    services                        business rules, permissions, audit
    export / importer / report      output formats and CSV import
    notify                          per-user digests
    cli                             argparse front end

See docs/ARCHITECTURE.md for how the pieces fit together.
"""

__version__ = "0.9.0"
