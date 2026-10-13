"""Media embeds — paste a provider link, get a player.

Named "media embeds" because "embeddings" already means vectors in Marvin (``services/ai/embeddings``).

- ``providers`` — the allow-listed provider registry (hosts, oEmbed endpoints, player builders).
- ``matcher`` — link → provider/target; pasted embed code → the link to store.
- ``extract`` — which links in an entry are media embeds (bare links in markdown, ``embed`` fields).
- ``resolver`` — oEmbed lookups through core's guarded HTTP client.
- ``cache`` — the platform-wide ``media_embed_cache`` table.
- ``html`` — the one escaped HTML builder (player, click-to-load facade, link card).
- ``publish`` — ``PublishedEmbed`` / ``site.embeds`` for the publishing API (reads the cache only).
"""
