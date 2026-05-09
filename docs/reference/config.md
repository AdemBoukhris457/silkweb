# Configuration

Set **`SILKWEB_STRICT_CONFIG=1`** (or `true` / `yes`) in the environment so `configure(...)` raises **`SilkwebConfigError`** on unknown top-level keys instead of storing them in `extra`.

::: silkweb.config.SilkwebConfig
    options:
      show_root_heading: true
      members_order: source
      show_source: true

::: silkweb.config.get_config
    options:
      show_root_heading: true

::: silkweb.config.configure
    options:
      show_root_heading: true
