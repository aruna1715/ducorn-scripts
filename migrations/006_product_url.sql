-- 006_product_url.sql
--
-- Where a deployed product actually lives.
--
-- The pipeline has never recorded this. A deploy printed ports to a terminal,
-- Slack got the same text, and the URL existed only in whoever was watching.
-- Come back the next morning and the only way to find a product you shipped is
-- to read a launchd plist.
--
-- product_url   the address to open — the LAN address, so it is clickable from
--               a phone on the same network rather than a localhost that means
--               nothing outside the Mac.
-- public_url    set only when a product has deliberately opted into a public
--               Cloudflare hostname. Separate from product_url so that
--               "deployed" never silently reads as "on the internet" — most
--               of these products ship with no authentication at all.

ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS product_url TEXT,
    ADD COLUMN IF NOT EXISTS public_url  TEXT;

COMMENT ON COLUMN pipeline_runs.product_url IS
    'LAN address of the deployed product, written by DuCornDeployTool.';
COMMENT ON COLUMN pipeline_runs.public_url IS
    'Public Cloudflare hostname, only when the product opted in via PUBLIC_HOSTNAME.';
