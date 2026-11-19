-- Give stock back to Redis for 1 order and remove its hold, as 1 step.
-- The caller makes sure this runs only once per order (Postgres decides that).
-- KEYS: stock:{p1}, ..., stock:{pN}, hold:{order_id}
-- ARGV: qty1, ..., qtyN
local n = #KEYS - 1
for i = 1, n do
  redis.call('INCRBY', KEYS[i], ARGV[i])
end
redis.call('DEL', KEYS[#KEYS])
return 1
