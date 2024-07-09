#!/bin/bash
export REDISCLI_AUTH="{{redis_password}}"
export SCRIPT=$(redis-cli SCRIPT LOAD "$(cat {{path_to_lua_script}})")
redis-cli EVALSHA $SCRIPT 0 $1 

