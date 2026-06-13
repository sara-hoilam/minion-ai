-- Add first and last name to user profiles
ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
  ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);

-- Backfill from existing full_name where possible
UPDATE user_profiles
SET
  first_name = split_part(trim(full_name), ' ', 1),
  last_name = CASE
    WHEN position(' ' in trim(full_name)) > 0
      THEN trim(substring(trim(full_name) from position(' ' in trim(full_name)) + 1))
    ELSE NULL
  END
WHERE full_name IS NOT NULL
  AND trim(full_name) <> ''
  AND (first_name IS NULL OR trim(first_name) = '')
  AND (last_name IS NULL OR trim(last_name) = '');
