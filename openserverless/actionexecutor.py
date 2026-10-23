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
import os, logging, json, time, math
import openserverless.couchdb_util as cu
import openserverless.kube as kube
import croniter as cn
import requests as req
from datetime import datetime

# Bound tenant-controlled input before passing it to the cron parser.
MAX_CRON_EXPRESSION_LENGTH = 4096

# Leave time for process shutdown before the Job's 120 second deadline.
HTTP_TIMEOUT = (3.0, 10.0)
RUN_BUDGET_SECONDS = 100.0
MAX_QUERY_PAGES = 1000
MAX_QUERY_DOCUMENTS = 25000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_QUERY_BYTES = 16 * 1024 * 1024


def request_timeout(deadline=None):
    if deadline is None:
        return HTTP_TIMEOUT
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError('Scheduler time budget exceeded')
    return tuple(min(value, remaining) for value in HTTP_TIMEOUT)

def check(f, what, res):
    if f:
        logging.info(f"OK: {what}")
        return res and True
    else:
        logging.warn(f"ERR: {what}")
        return False

#
# extract the configured interval between
# two consecutive execution of this process
# scheduled via the openserverless cron component
#
def from_cron_to_seconds(base, cronExpr):
    """
        >>> import openserverless.actionexecutor as ae
        >>> from datetime import datetime
        >>> base = datetime.now()
        >>> ae.from_cron_to_seconds(base,'* * * * *')
        60.0
        >>> ae.from_cron_to_seconds(base,'*/30 * * * *')
        1800.0
    """    
    itr = cn.croniter(cronExpr, base)
    nextTime1 = itr.get_next(datetime)
    nextTime2 = itr.get_next(datetime)
    diff = nextTime2 - nextTime1
    return diff.total_seconds()

#
# Check if an action with the specified cron expression
# should have been triggered since the last execution of this scheduled job.
#
def action_should_trigger(currentDate, executionInterval, actionCronExpression):
    """
        >>> import openserverless.actionexecutor as ae
        >>> from datetime import datetime
        >>> base = datetime.now()
        >>> base1 = datetime(2022, 8, 6, 16, 30, 0, 0)          
        >>> base2 = datetime(2022, 8, 6, 16, 00, 0, 0) 
        >>> base3 = datetime(2022, 8, 6, 16, 3, 0, 0)
        >>> base4 = datetime(2022, 8, 6, 16, 10, 0, 0) 
        >>> ae.action_should_trigger(base,60,'* * * * *')
        True
        >>> ae.action_should_trigger(base1, 60,'*/30 * * * *')
        True
        >>> ae.action_should_trigger(base2, 60,'*/30 * * * *')
        True
        >>> ae.action_should_trigger(base3, 60,'*/5 * * * *')
        False
        >>> ae.action_should_trigger(base4, 60,'*/5 * * * *')
        True
    """ 
    currentTimestamp = datetime.timestamp(currentDate)
    prevTimestamp = currentTimestamp - executionInterval
    prevDate = datetime.fromtimestamp(prevTimestamp)

    result = False

    for dt in cn.croniter_range(prevDate, currentDate, actionCronExpression):
        if(dt):
            result = True
            break

    return result

#
# query the dbn database using the specified selecto
#
def find_docs(db, dbn, selector, username, password, deadline=None):
    documents = []
    query = json.loads(selector)
    logging.info(f"Querying couchdb {dbn} for documents")

    if deadline is None:
        deadline = time.monotonic() + RUN_BUDGET_SECONDS
    seen_bookmarks = set()
    total_bytes = 0
    for _ in range(MAX_QUERY_PAGES):
        res = db.find_doc(dbn, json.dumps(query), username, password,
                          timeout=request_timeout(deadline), raise_on_error=True,
                          max_response_bytes=MAX_RESPONSE_BYTES, deadline=deadline)
        request_timeout(deadline)
        if not isinstance(res, dict) or not isinstance(res.get('docs'), list):
            raise RuntimeError('Invalid CouchDB pagination response')
        total_bytes += len(json.dumps(res).encode('utf-8'))
        if total_bytes > MAX_QUERY_BYTES:
            raise RuntimeError('CouchDB query byte limit exceeded')
        docs = res['docs']
        if not docs:
            return documents
        if not all(isinstance(doc, dict) for doc in docs):
            raise RuntimeError('Invalid CouchDB document')
        bookmark = res.get('bookmark')
        if (not isinstance(bookmark, str) or not bookmark
                or bookmark == query.get('bookmark') or bookmark in seen_bookmarks):
            raise RuntimeError('CouchDB pagination did not advance')
        if len(documents) + len(docs) > MAX_QUERY_DOCUMENTS:
            raise RuntimeError('CouchDB query document limit exceeded')
        seen_bookmarks.add(bookmark)
        documents.extend(docs)
        query['bookmark'] = bookmark
    raise RuntimeError('CouchDB pagination page limit exceeded')

#
# Get subject from openserverless_subjects db
#
#TODO need to find a way to build a dictionary with dynamic key or a hashmap
def get_subjects(db, username, password, deadline=None):
    subjects = []
    selector = '{"selector":{"subject": {"$exists": true}},"fields":["namespaces"]}'
    namespaces = find_docs(db, "subjects", selector, username, password, deadline)

    for entry in namespaces:
        currentNamespaceList = list(entry['namespaces'])
        for namespace in currentNamespaceList:            
            subjects.append(namespace);            

    return list(subjects)

#
# get actions from the openserverless_whisks db
# having an annotation with key=cron or key=autoexec and value=true
#
def get_cron_aware_actions(db, username, password, deadline=None):
    selector = '{"selector":{"entityType":"action", "$or":[{"annotations": {"$elemMatch": {"key": "cron"}}},{"annotations": {"$elemMatch": {"$and":[{"key":"autoexec"},{"value":true}]}}}] }, "fields": ["_id", "annotations", "name", "_rev","namespace","parameters","entityType"]}'
    return find_docs(db, "whisks", selector, username, password, deadline)
#
# POST a request to invoke the ow action
#
def call_ow_action(url, parameters, ow_auth, deadline=None):
    logging.info(f"POST request to {url}")
    headers = {'Content-Type': 'application/json'}

    try:
        response = None
        if(len(parameters)>0):
            logging.info("calling an action with %s parameters",len(parameters))
        
        # OpenWhisk passes automatically the registered parameters, so this cron executor does not need to pass them.
        response = req.post(url, auth=(ow_auth['username'],ow_auth['password']),
                            timeout=request_timeout(deadline), stream=True,
                            allow_redirects=False)

        if (response.status_code in [200,202]):
            logging.info(f"call to {url} succeeded with {response.status_code}")
            return True        
            
        logging.warning(f"call to {url} failed with {response.status_code}")
        return False
    except Exception as inst:
        logging.warning("Invocation request failed; acceptance may be uncertain; not retrying: %s", inst)
        return False
    finally:
        if response is not None:
            response.close()

#
# Update the action annotations to disable the cron execution
# by setting {"autoexec":false}
#        
def unschedule_autoexec_action(action_url, ow_auth, deadline=None):
    logging.info(f"Purging cron details from action {action_url}")    
    headers = {'Content-Type': 'application/json'}

    response = None
    try:
        updating_data = {}
        updated_annotation = [{"key":"autoexec","value":False}]
        updating_data["annotations"]=updated_annotation
        logging.info(f"updating with {json.dumps(updating_data)}")
        
        response = req.put(f"{action_url}?overwrite=true", auth=(ow_auth['username'],ow_auth['password']), headers=headers, data=json.dumps(updating_data),
                           timeout=request_timeout(deadline), stream=True,
                           allow_redirects=False)

        if response.status_code != 200:
            logging.warning(f"PUT call to {action_url}?overwrite=true failed with {response.status_code}")
            return False

        logging.info(f"PUT call to {action_url}?overwrite=true succeeded with {response.status_code}. Action cron policy removed")
        return True
    except Exception as inst:
        logging.warn(f"Failed to invoke action {type(inst)}")
        logging.warn(inst)
        return False
    finally:
        if response is not None:
            response.close()

#
# Extract the cron expression from the given annotations list
#
def get_cron_expression(actionAnnotations):
    """
        >>> import openserverless.actionexecutor as ae 
        >>> annotations = []
        >>> annotations.append({"key":"cron","value":"*/2 * * * *"})
        >>> annotations.append({"key":"provide-api-key","value":False})            
        >>> annotations.append({"key":"exec","value":"nodejs:14"})
        >>> "*/2 * * * *" == ae.get_cron_expression(annotations)
        True
        >>> "once" == ae.get_cron_expression([{"key":"cron","value":"once"}])
        True
    """
    for a in actionAnnotations:
        if(a['key'] == 'cron'):
            return a['value']

    return None

#
# Extract the autoexect flag from the given annotations list
#
def get_autoexec(actionAnnotations):
    """
        >>> import openserverless.actionexecutor as ae 
        >>> annotations = []
        >>> annotations.append({"key":"autoexec","value":True})
        >>> annotations.append({"key":"provide-api-key","value":False})            
        >>> annotations.append({"key":"exec","value":"nodejs:14"})
        >>> ae.get_autoexec(annotations)
        True
        >>> ae.get_autoexec([{"key":"autoexec","value":False}])
        False
    """
    for a in actionAnnotations:
        if(a['key'] == 'autoexec'):
            return a['value']

    return False    

#
# Determine if the action should be triggered
# possible return values are
# execute if the action should be triggered according to current date
# no_execution if the action should not be triggered or the cron expression is not a valid one
#
def should_trigger(actionNamespace, actionName, actionCronExpression, currentDate, executionInterval):
    if (not isinstance(actionCronExpression, str)
            or not 0 < len(actionCronExpression) <= MAX_CRON_EXPRESSION_LENGTH
            or not cn.croniter.is_valid(actionCronExpression)):
        logging.warning("action %s/%s has an invalid cron expression. Skipping execution",
                        actionNamespace, actionName)
        return "no_execution"

    if not action_should_trigger(currentDate, executionInterval, actionCronExpression):
        logging.warn(f"action {actionNamespace}/{actionName} cron expression {actionCronExpression} does not trigger an execution at {currentDate}")
        return "no_execution"
    
    return "execute"

def build_action_url(baseurl,namespace, package, action_name):
    """
        >>> import openserverless.actionexecutor as ae         
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","openserverless","mongo","mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/openserverless/actions/mongo/mongo"
        True
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","openserverless",None,"mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/openserverless/actions/mongo"
        True
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","openserverless","","mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/openserverless/actions/mongo"
        True
    """    
    url = f"{baseurl}{namespace}/actions/"
    if package:
        url += f"{package}/"

    url += action_name    
    return url  

def get_package_from_namespace(action_namespace):
    """
        >>> import openserverless.actionexecutor as ae         
        >>> package = ae.get_package_from_namespace("openserverless")
        >>> package == ""
        True
        >>> package = ae.get_package_from_namespace("openserverless/mongo")
        >>> package == "mongo"
        True
        >>> package = ae.get_package_from_namespace("openserverless/mongo/mongo")
        >>> package == "mongo/mongo"
        True
    """    
    parts = action_namespace.partition("/")

    if parts[2]:
        return parts[2]

    return ""

def get_subject(action_namespace):
    """
        >>> import openserverless.actionexecutor as ae         
        >>> package = ae.get_subject("openserverless")
        >>> package == "openserverless"
        True
        >>> package = ae.get_subject("openserverless/mongo")
        >>> package == "openserverless"
        True
        >>> package = ae.get_subject("openserverless/mongo/mongo")
        >>> package == "openserverless"
        True
    """    
    return action_namespace.partition("/")[0]
#
# Evaluate if the given whisk action must be executed or not
# 
# dAction input is a json Object with similar structure.
# 
# dAction = '{"_id":"openserverless/hello-cron-action","annotations":[{"key":"cron","value":"*/2 * * * *"},{"key":"provide-api-key","value":false},{"key":"exec","value":"nodejs:14"}],"name":"hello-cron-action","_rev":"1-19f424e1fec1c02a2ecccf6f90978e31","namespace":"openserverless","parameters":[],"entityType":"action"}'
def handle_action(baseurl, currentDate, executionInterval, dAction, subjects, deadline=None):
    actionName = dAction['name']
    entityType = dAction['entityType']
    actionNamespace = dAction['namespace']
    actionParameters = list(dAction['parameters'])
    actionAnnotations = list(dAction['annotations'])

    autoexecAction = get_autoexec(actionAnnotations)
    execute = "no_execution"

    #gives always precedence to the autoexec annotations
    if autoexecAction:
        execute = "execute_once"
    else:
        actionCronExpression = get_cron_expression(actionAnnotations)
        execute = should_trigger(actionNamespace,actionName,actionCronExpression,currentDate,executionInterval)

    if "no_execution" == execute:
        return True

    namespaceSubject = get_subject(actionNamespace)
    auth = get_auth(subjects, namespaceSubject)
    if(auth):
        package = get_package_from_namespace(actionNamespace)
        
        base_action_url = build_action_url(baseurl,namespaceSubject, package, actionName)        
        ret = call_ow_action(f"{base_action_url}?blocking=false&result=false", actionParameters, auth, deadline)

        if ret and "execute_once" == execute:
            return unschedule_autoexec_action(base_action_url, auth, deadline)
        return ret
    else:
        logging.warning('No subject %s credentials found!', namespaceSubject)
    return False

#
# Search and return a {'username':'xxx','passowrd':'xxx'} dictionary
#
def get_auth(subjects, subjectName):
    for subject in subjects:
        if(subject['name'] == subjectName):
            return {'username':subject['uuid'], 'password':subject['key']}
        
    return None


#
# Will queries the internal CouchDB for cron aware actions
# to be triggered since the last execution time.
# TODO the interval execution time must be parametrized.
# Implement the logic to query for actions and evaluate how to execute them
#
def start():
    deadline = time.monotonic() + RUN_BUDGET_SECONDS
    logging.basicConfig(level=logging.INFO)
    try:
        return run(deadline)
    except Exception:
        logging.exception('Scheduler run failed; no automatic replay')
        return 1


def run(deadline):
    # load scheduler config from the os environment
    cfg = os.environ.get("SCHEDULER_CONFIG")
    if not cfg:
        raise ValueError('SCHEDULER_CONFIG is required')
    config = json.loads(cfg)

    currentDate = datetime.now()
    interval = from_cron_to_seconds(currentDate, config['scheduler.schedule'])
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError('Scheduler interval must be finite and positive')
    logging.info(f"interval in seconds between 2 execution is {interval} seconds")

    db = cu.CouchDB()
    res = check(db.wait_db_ready(30), "wait_db_ready", True)

    if(res):
        ow_protocol = config['controller.protocol']
        ow_host = config['controller.host']
        ow_port = config['controller.port']
        baseurl = f"{ow_protocol}://{ow_host}:{ow_port}/api/v1/namespaces/"                
        actions = get_cron_aware_actions(db, config['couchdb.controller.user'],config['couchdb.controller.password'], deadline)

        if(len(actions) > 0):
            subjects = get_subjects(db, config['couchdb.controller.user'],config['couchdb.controller.password'], deadline)
            failed = False
            for action in actions:
                request_timeout(deadline)
                try:
                    if not handle_action(baseurl, currentDate, interval, action, subjects, deadline):
                        failed = True
                except Exception:
                    failed = True
                    logging.exception("Failed to process scheduled action; continuing with remaining actions")
            return 1 if failed else 0
        else:
            logging.info('No cron aware action extracted. Exiting....')
            return 0
    else:
        logging.warn("CouchDB it is not available. Exiting....")
        return 1
