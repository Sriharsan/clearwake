# Upstream notice

Clearwake uses the public Relayloom project as a Git submodule at
`vendor/relayloom`, pinned to `3668d316878e578223b8255622300c5d6131e5e3`.
Source: https://github.com/Sriharsan/relayloom
Copyright 2026 Sriharsan B S. MIT license retained in the submodule.

The workroom controller, scheduler, role/session/CSRF/SSE boundaries, base UI,
optional Meta adapter and their upstream tests are reused public work. Clearwake
subclasses the controller/server and adds reviewed runtime UI event hooks; it
does not copy private Verdock source or claim that the shared core is new
PayPal-specific work. PayPal API schemas/documentation informed the adapter;
no PayPal SDK or copied third-party implementation is bundled.
