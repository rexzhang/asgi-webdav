# How to Specify Type for specific file extentions

change your `webdav.json` like blow:

```json
{
  "guess_type_extension": {
    "filename_mapping": {
      ".bashrc": "text/plain"
    },
    "suffix_mapping": {
      ".py": "text/plain"
    }
  }
}
```

default value DEFAULT_FILENAME_CONTENT_TYPE_MAPPING and DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING defined in file `constants.py` .