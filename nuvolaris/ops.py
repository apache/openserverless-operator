# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
import os


def directory(*args):
    """
    Constructs a directory path by concatenating provided arguments and optionally
    prepends a prefix obtained from the environment variable OPERATOR_DIR_PREFIX.

    This function is intended to be used as a temporary helper for transitioning to the next version of the operator.

    Parameters:
    args: str
        Variable-length arguments representing directory names to be joined.

    Returns:
    str
        A concatenated and possibly prefixed directory path.
    """
    result = "/".join(args)
    prefix = os.environ.get("OPERATOR_DIR_PREFIX")
    if prefix:
        result = f"{prefix}/{result}"
    return result
