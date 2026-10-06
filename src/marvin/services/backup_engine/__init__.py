"""Backups of a Marvin installation to backup targets (built-in ``local``, or a storage plugin's).

``engine`` backs up the database, the config archive and an asset mirror to one target, restores and
prunes; ``layout`` holds the key layout and retention; ``local_target`` is the built-in target, a
directory on a second volume. Run it with ``python -m marvin.scripts.backup``, one CronJob per target.
Kept free of Marvin's settings and database imports: it runs beside the live backend.
"""
