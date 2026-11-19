#!/bin/sh
# Starts a single SeaweedFS node (master, volume, filer and S3 gateway in 1 process).
set -eu

cat > /tmp/s3.json <<JSON
{
  "identities": [
    {
      "name": "orderflow",
      "credentials": [{ "accessKey": "${S3_ACCESS_KEY}", "secretKey": "${S3_SECRET_KEY}" }],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
JSON

# -ip=s3 is the name other containers use; -ip.bind=0.0.0.0 listens on every address.
exec weed server -dir=/data -ip=s3 -ip.bind=0.0.0.0 \
  -s3 -s3.port=8333 -s3.config=/tmp/s3.json \
  -master.volumeSizeLimitMB=64 -volume.max=0
