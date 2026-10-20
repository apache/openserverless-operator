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

import re


def tenant_rules(prefix, readonly=False):
    """Replace tenant grants, including legacy key/channel grants and selectors."""
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}:', prefix):
        raise ValueError('Invalid Redis tenant prefix')
    rules = ['-@all', 'resetkeys', 'resetchannels', 'clearselectors', '+@read', '+@transaction']
    if readonly:
        rules += ['+del', '+unlink', '+subscribe', '+psubscribe', '+unsubscribe',
                  '+punsubscribe', '+ssubscribe', '+sunsubscribe']
    else:
        rules += ['+@write', '+@pubsub']
    rules += ['-@admin', '-@dangerous', '-@scripting', '-keys', '-scan', '-dbsize',
              '-randomkey', '-sort', '-sort_ro', '-pubsub', '+ping', '+echo', '+hello',
              '+auth', '+quit', '+client|setname', '+client|setinfo', '+client|id',
              '~' + prefix + '*', '&' + prefix + '*',
              '+eval', '+evalsha', '+eval_ro', '+evalsha_ro', '+script|load', '+script|exists']
    return rules
