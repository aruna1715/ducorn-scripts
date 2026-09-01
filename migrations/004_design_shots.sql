-- 004: where the picture of each design variant lives.
--
-- Gate 2 used to post three links. Opening three tabs to make a purely visual
-- decision is enough friction that the decision gets made without looking, so
-- the gate now uploads the images and the row records which file to upload.
--
-- Nullable on purpose: a variant whose screenshot failed is still a variant,
-- and the gate says so rather than refusing to post.

ALTER TABLE design_variants
    ADD COLUMN IF NOT EXISTS shot_path text;
