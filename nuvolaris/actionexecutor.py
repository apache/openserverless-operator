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
import os, logging, json
import nuvolaris.couchdb_util as cu
import nuvolaris.kube as kube
import croniter as cn
import requests as req
from datetime import datetime

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
# scheduled via the nuvolaris cron component
#
def from_cron_to_seconds(base, cronExpr):
    """
        >>> import nuvolaris.actionexecutor as ae
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
        >>> import nuvolaris.actionexecutor as ae
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
def find_docs(db, dbn, selector, username, password):
    documents = []
    query = json.loads(selector)
    logging.info(f"Querying couchdb {dbn} for documents")

    #CouchDB returns no more than 25 records. We iterate to get all the cron enabled actions.
    while(True):
        logging.info(f"select query param {json.dumps(query)}")
        res = db.find_doc(dbn, json.dumps(query), username, password)

        if(res == None):
            break

        if(res['docs']):
            docs = list(res['docs'])
            if(len(docs) > 0):
                documents.extend(docs)
                if(res['bookmark']):
                    query['bookmark']=res['bookmark']                
            else:
                logging.info('docs item is an emtpy list. No more documents found')
                break 
        else:
            logging.info('docs items not present. no more documents found')
            break 
       
    return list(documents)

#
# Get subject from nuvolaris_subjects db
#
#TODO need to find a way to build a dictionary with dynamic key or a hashmap
def get_subjects(db, username, password):
    subjects = []
    selector = '{"selector":{"subject": {"$exists": true}},"fields":["namespaces"]}'
    namespaces = find_docs(db, "subjects", selector, username, password)

    for entry in namespaces:
        currentNamespaceList = list(entry['namespaces'])
        for namespace in currentNamespaceList:            
            subjects.append(namespace);            

    return list(subjects)

#
# get actions from the nuvolaris_whisks db
# having an annotation with key=cron or key=autoexec and value=true
#
def get_cron_aware_actions(db, username, password):
    selector = '{"selector":{"entityType":"action", "$or":[{"annotations": {"$elemMatch": {"key": "cron"}}},{"annotations": {"$elemMatch": {"$and":[{"key":"autoexec"},{"value":true}]}}}] }, "fields": ["_id", "annotations", "name", "_rev","namespace","parameters","entityType"]}'
    return find_docs(db, "whisks", selector, username, password)
#
# POST a request to invoke the ow action
#
def call_ow_action(url, parameters, ow_auth):
    logging.info(f"POST request to {url}")
    headers = {'Content-Type': 'application/json'}

    try:
        response = None
        if(len(parameters)>0):
            response = req.post(url, auth=(ow_auth['username'],ow_auth['password']), headers=headers, data=json.dumps(parameters))
        else:
            #If the body is empty Content-Type must be not provided otherwise OpenWhisk api returns a 400 error    
            response = req.post(url, auth=(ow_auth['username'],ow_auth['password']))

        if (response.status_code in [200,202]):
            logging.info(f"call to {url} succeeded with {response.status_code}. Body {response.text}")
            return True        
            
        logging.warn(f"query to {url} failed with {response.status_code}. Body {response.text}")
        return False
    except Exception as inst:
        logging.warn(f"Failed to invoke action {type(inst)}")
        logging.warn(inst)
        return False

#
# Update the action annotations to disable the cron execution
# by setting {"autoexec":false}
#        
def unschedule_autoexec_action(action_url, ow_auth):   
    logging.info(f"Purging cron details from action {action_url}")    
    headers = {'Content-Type': 'application/json'}

    try:
        updating_data = {}
        updated_annotation = [{"key":"autoexec","value":False}]
        updating_data["annotations"]=updated_annotation
        logging.info(f"updating with {json.dumps(updating_data)}")
        
        response = req.put(f"{action_url}?overwrite=true", auth=(ow_auth['username'],ow_auth['password']), headers=headers, data=json.dumps(updating_data))

        if response.status_code != 200:
            logging.warn(f"PUT call to {action_url}?overwrite=true failed with {response.status_code}. Body {response.text}")
            return False

        logging.info(f"PUT call to {action_url}?overwrite=true succeeded with {response.status_code}. Action cron policy removed")
        return True
    except Exception as inst:
        logging.warn(f"Failed to invoke action {type(inst)}")
        logging.warn(inst)
        return False       

#
# Extract the cron expression from the given annotations list
#
def get_cron_expression(actionAnnotations):
    """
        >>> import nuvolaris.actionexecutor as ae 
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
        >>> import nuvolaris.actionexecutor as ae 
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
    if not cn.croniter.is_valid(actionCronExpression):
        logging.warn(f"action {actionNamespace}/{actionName} cron expression {actionCronExpression} is not valid. Skipping execution")
        return "no_execution"

    if not action_should_trigger(currentDate, executionInterval, actionCronExpression):
        logging.warn(f"action {actionNamespace}/{actionName} cron expression {actionCronExpression} does not trigger an execution at {currentDate}")
        return "no_execution"
    
    return "execute"

def build_action_url(baseurl,namespace, package, action_name):
    """
        >>> import nuvolaris.actionexecutor as ae         
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","nuvolaris","mongo","mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/nuvolaris/actions/mongo/mongo"
        True
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","nuvolaris",None,"mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/nuvolaris/actions/mongo"
        True
        >>> url = ae.build_action_url("http://localhost:3233/api/v1/namespaces/","nuvolaris","","mongo")
        >>> url == "http://localhost:3233/api/v1/namespaces/nuvolaris/actions/mongo"
        True
    """    
    url = f"{baseurl}{namespace}/actions/"
    if package:
        url += f"{package}/"

    url += action_name    
    return url  

def get_package_from_namespace(action_namespace):
    """
        >>> import nuvolaris.actionexecutor as ae         
        >>> package = ae.get_package_from_namespace("nuvolaris")
        >>> package == ""
        True
        >>> package = ae.get_package_from_namespace("nuvolaris/mongo")
        >>> package == "mongo"
        True
        >>> package = ae.get_package_from_namespace("nuvolaris/mongo/mongo")
        >>> package == "mongo/mongo"
        True
    """    
    parts = action_namespace.partition("/")

    if parts[2]:
        return parts[2]

    return ""

def get_subject(action_namespace):
    """
        >>> import nuvolaris.actionexecutor as ae         
        >>> package = ae.get_subject("nuvolaris")
        >>> package == "nuvolaris"
        True
        >>> package = ae.get_subject("nuvolaris/mongo")
        >>> package == "nuvolaris"
        True
        >>> package = ae.get_subject("nuvolaris/mongo/mongo")
        >>> package == "nuvolaris"
        True
    """    
    return action_namespace.partition("/")[0]
#
# Evaluate if the given whisk action must be executed or not
# 
# dAction input is a json Object with similar structure.
# 
# dAction = '{"_id":"nuvolaris/hello-cron-action","annotations":[{"key":"cron","value":"*/2 * * * *"},{"key":"provide-api-key","value":false},{"key":"exec","value":"nodejs:14"}],"name":"hello-cron-action","_rev":"1-19f424e1fec1c02a2ecccf6f90978e31","namespace":"nuvolaris","parameters":[],"entityType":"action"}'
def handle_action(baseurl, currentDate, executionInterval, dAction, subjects):  
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
        return None

    namespaceSubject = get_subject(actionNamespace)
    auth = get_auth(subjects, namespaceSubject)
    if(auth):
        package = get_package_from_namespace(actionNamespace)
        
        base_action_url = build_action_url(baseurl,namespaceSubject, package, actionName)        
        ret = call_ow_action(f"{base_action_url}?blocking=false&result=false", actionParameters, auth)

        if ret and "execute_once" == execute:
            unschedule_autoexec_action(base_action_url, auth)
    else:
        logging.warn('No subject {subjectName} credentials found!')
    return None

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
    # load scheduler config from the os environment
    cfg = os.environ.get("SCHEDULER_CONFIG")
    if cfg:        
        logging.basicConfig(level=logging.INFO)
        config = json.loads(cfg)        

    currentDate = datetime.now()
    interval = from_cron_to_seconds(currentDate, config['scheduler.schedule'])
    logging.info(f"interval in seconds between 2 execution is {interval} seconds")

    db = cu.CouchDB()
    res = check(db.wait_db_ready(30), "wait_db_ready", True)

    if(res):
        ow_protocol = config['controller.protocol']
        ow_host = config['controller.host']
        ow_port = config['controller.port']
        baseurl = f"{ow_protocol}://{ow_host}:{ow_port}/api/v1/namespaces/"                
        actions = get_cron_aware_actions(db, config['couchdb.controller.user'],config['couchdb.controller.password'])

        if(len(actions) > 0):
            subjects = get_subjects(db, config['couchdb.controller.user'],config['couchdb.controller.password'])
            for action in actions:
                handle_action(baseurl, currentDate, interval, action, subjects)
        else:
            logging.info('No cron aware action extracted. Exiting....')
    else:
        logging.warn("CouchDB it is not available. Exiting....")