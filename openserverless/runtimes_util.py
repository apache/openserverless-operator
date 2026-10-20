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
import kopf, logging, time, os
import openserverless.kube as kube
import openserverless.kustomize as kus
import openserverless.config as cfg
import openserverless.util as util

# Kinds whose version is this suffix are always preloaded, whether or not they
# are the default for their family. The system actions deployed by
# whisk_actions_deployer run on python:sys, so such images must be on the node
# before the first invocation.
ALWAYS_PRELOADED_SUFFIX = "sys"


def add_container(containers: list, container_name, runtime):
    """ Append a preloader container entry for a runtime, if it has a usable image.
    Images are preloaded whatever registry or organization they come from.
    :param containers, the global containers array
    :param container_name, the name that will be assigned for the containers preloader
    :param runtime, the single runtime entry to add
    """
    img = runtime['image']
    if not img.get('tag'):
        logging.warning(f"skipping runtime preloader for {container_name}: missing image tag")
        return
    container = {
        "name": container_name,
        "image": f"{img['prefix']}/{img['name']}:{img['tag']}"
        }
    containers.append(container)


def find_default_container(containers: list, container_name, runtime_list):
    """ Scans for the inner runtime list and add an entry into the containers for the default one if any
    :param containers, the global containers array
    :param container_name, the name that will be assigned for the containers preloader
    :param runtime_list the where to find for the default runtime if any
    """
    for runtime in runtime_list:        
        if runtime['default']:
            add_container(containers, container_name, runtime)


def find_always_preloaded_containers(containers: list, container_name, runtime_list):
    """ Adds every `<family>:sys` kind, which is preloaded even when it is not the
    default of its family. A kind already added as the default is not added twice.
    :param containers, the global containers array
    :param container_name, the family name, used to build the container name
    :param runtime_list the runtime list where to look for the kinds
    """
    for runtime in runtime_list:
        kind = runtime.get('kind') or ''
        if not kind.endswith(f":{ALWAYS_PRELOADED_SUFFIX}") or runtime.get('default'):
            continue
        name = kind.replace(':', '-').replace('.', '-')
        if any(c['name'] == name for c in containers):
            continue
        add_container(containers, name, runtime)

def parse_runtimes(runtimes_as_json):
    """ parse an openwhisk runtimes json and returns a stuitable data structure to customize the preloader jon

    Every default kind is preloaded, plus every `<family>:sys` kind, whatever
    registry or organization the image comes from.
    :param runtimes_as_json a runtime json typically extracted from a config map
    >>> import openserverless.testutil as tutil
    >>> runtimes_as_json = tutil.load_sample_runtimes()
    >>> data = parse_runtimes(runtimes_as_json)
    >>> len(data['containers']) == 8
    True
    """
    data = {}
    containers = list()

    for name in runtimes_as_json["runtimes"]:        
        find_default_container(containers, name, runtimes_as_json["runtimes"][name])
        find_always_preloaded_containers(containers, name, runtimes_as_json["runtimes"][name])
           
    data['containers']=containers
    return data
