-- Licensed to the Apache Software Foundation (ASF) under one
-- or more contributor license agreements.  See the NOTICE file
-- distributed with this work for additional information
-- regarding copyright ownership.  The ASF licenses this file
-- to you under the Apache License, Version 2.0 (the
-- "License"); you may not use this file except in compliance
-- with the License.  You may obtain a copy of the License at
--
--   http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing,
-- software distributed under the License is distributed on an
-- "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
-- KIND, either express or implied.  See the License for the
-- specific language governing permissions and limitations
-- under the License.
--
-- Define the key prefix to search for
local prefix = ARGV[1]
local cursor = 0
local total_memory = 0

repeat
    -- Use SCAN to get keys that match the prefix
    local result = redis.call('SCAN', cursor, 'MATCH', prefix .. '*')
    cursor = tonumber(result[1])
    local keys = result[2]

    for _, key in ipairs(keys) do
        -- Get memory usage of each key and add it to the total
        local memory_usage = redis.call('MEMORY', 'USAGE', key)
        if memory_usage then
            total_memory = total_memory + memory_usage
        end
    end
until cursor == 0

return total_memory