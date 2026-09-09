# OpenWF H.Cache Rebuilder

Reconstruct the missing OpenWF H.Cache override for a historical Warframe build from its active `B.Cache.*.bin!E_<hash>` manifests.

The tool creates these files in the same folder as the selected manifests:

```text
H.Cache.bin!E_---------------------w
UNMANAGED
```

## Recommended usage

Select **all active `B.Cache.*.bin!E_<hash>` files for one Warframe build** and drag them together onto:

```text
rebuild_hcache_drag_drop.bat
```

Do **not** drag only `B.Cache.Windows.bin` if you want a historically complete H.Cache. `H.Cache.bin` also references the active DirectX and language manifests, so include the active `B.Cache.*` file for every logical manifest used by that build.

For example, a build may include:

```text
B.Cache.Windows.bin!E_<hash>
B.Cache.Dx11.bin!E_<hash>
B.Cache.Dx12.bin!E_<hash>
B.Cache.Windows_en.bin!E_<hash>
B.Cache.Windows_de.bin!E_<hash>
...
```

## Command-line usage

You can also run the Python script directly:

```bat
python rebuild_hcache.py B.Cache.Windows.bin!E_HASH B.Cache.Dx11.bin!E_HASH ...
```

Or give it one directory containing a clean, unambiguous set of active manifests:

```bat
python rebuild_hcache.py "D:\Patch\OpenWF\Content\0"
```

To write the generated files somewhere else:

```bat
python rebuild_hcache.py <files...> --output "D:\Output"
```

## Existing H.Cache files

Existing H.Cache overrides are protected by default. The tool refuses to replace:

```text
H.Cache.bin!E_---------------------w
```

Use `--force` only when you intentionally want to rebuild an existing override.

## UNMANAGED

`UNMANAGED` is a zero-byte marker that tells the OpenWF Bootstrapper to trust the supplied H.Cache instead of reconstructing or replacing it from the installation's `H.Misc` cache.

## Requirements

- Python 3.10 or newer
- No third-party Python packages
