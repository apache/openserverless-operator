"""
Apache Spark Operator for OpenServerless

This operator manages Apache Spark cluster deployment including:
- Spark Master (high availability optional)
- Spark Workers
- Spark History Server
- Resource management and scaling
"""

import kopf
import logging
import nuvolaris.kustomize as kus
import nuvolaris.kube as kube
import nuvolaris.config as cfg
import nuvolaris.util as util
import nuvolaris.template as ntp
import nuvolaris.operator_util as operator_util
import time
import subprocess


def get_spark_config_data():
    """
    Collect Spark configuration from CRD spec
    
    Returns:
        Dict with complete Spark configuration
    """
    namespace = cfg.get('nuvolaris.namespace', defval='nuvolaris')
    
    # Nota: config.get accetta il nome del parametro defval e NON "default".
    # Le chiamate precedenti con default= generavano TypeError e impedivano la creazione del cluster Spark.
    data = {
        # Basic configuration
        "name": "spark",
        "namespace": namespace,
        
        # Spark images
        "spark_image": cfg.get('spark.image', defval='apache/spark:3.5.0'),
        "spark_version": cfg.get('spark.version', defval='3.5.0'),
        
        # Master configuration
        "master_replicas": cfg.get('spark.master.replicas', defval=1),
        "master_memory": cfg.get('spark.master.memory', defval='1g'),
        "master_cpu": cfg.get('spark.master.cpu', defval='1000m'),
        "master_port": cfg.get('spark.master.port', defval=7077),
        "master_webui_port": cfg.get('spark.master.webui-port', defval=8080),
        
        # Worker configuration
        "worker_replicas": cfg.get('spark.worker.replicas', defval=2),
        "worker_memory": cfg.get('spark.worker.memory', defval='2g'),
        "worker_cpu": cfg.get('spark.worker.cpu', defval='2000m'),
        "worker_cores": cfg.get('spark.worker.cores', defval=2),
        "worker_webui_port": cfg.get('spark.worker.webui-port', defval=8081),
        
        # History Server configuration
        "history_enabled": cfg.get('spark.history-server.enabled', defval=True),
        "history_port": cfg.get('spark.history-server.port', defval=18080),
        "history_volume_size": cfg.get('spark.history-server.volume-size', defval=10),
        
        # Storage configuration
        "event_log_enabled": cfg.get('spark.event-log.enabled', defval=True),
        "event_log_dir": cfg.get('spark.event-log.dir', defval='/tmp/spark-events'),
        "storage_class": cfg.get("nuvolaris.storageclass"),
        
        # High Availability (optional)
        "ha_enabled": cfg.get('spark.ha.enabled', defval=False),
        "ha_zookeeper_url": cfg.get('spark.ha.zookeeper-url', defval=''),
        
        # Standard OpenServerless patterns
        "affinity": cfg.get('affinity', defval=False),
        "affinity_core_node_label": cfg.get('affinity-core-node-label', defval='nuvolaris'),
        "tolerations": cfg.get('tolerations', defval=False),
        
        # Security (standard pattern)
        "spark_user": cfg.get('spark.user', defval='spark'),
        "spark_uid": cfg.get('spark.uid', defval=185),
    }
    
    # Add standard OpenServerless affinity/tolerations data
    util.couch_affinity_tolerations_data(data)
    
    return data


def create(owner=None):
    """
    Deploy Apache Spark cluster on Kubernetes using standard OpenServerless patterns
    """
    logging.info("*** creating spark cluster")
    
    # Apply all manifests in deploy/spark directory directly (exclude non-K8s files)
    import glob
    import os
    
    spark_dir = "deploy/spark"
    yaml_files = glob.glob(f"{spark_dir}/*.yaml")
    yaml_files.sort()  # Apply in alphabetical order
    
    all_manifests = []
    for yaml_file in yaml_files:
        filename = os.path.basename(yaml_file)
        # Skip CRD extension files and kustomization files
        if filename in ["kustomization.yaml", "spark-crd-extension.yaml"]:
            continue
            
        with open(yaml_file, 'r') as f:
            content = f.read()
            # Parse YAML content
            import yaml
            docs = list(yaml.load_all(content, yaml.SafeLoader))
            for doc in docs:
                if doc and 'kind' in doc and 'apiVersion' in doc:  # Valid K8s manifest
                    all_manifests.append(doc)
    
    # Create the list object for kubectl apply
    spec = {
        "apiVersion": "v1", 
        "kind": "List", 
        "items": all_manifests
    }
    
    # 3. Apply owner reference for garbage collection  
    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.spark.spec", spec)
    
    # 5. Deploy to Kubernetes
    res = kube.apply(spec)
    logging.info("spark manifests applied")
    
    # 6. Wait for components to be ready
    logging.info("waiting for spark master to be ready...")
    util.wait_for_pod_ready(
        "{.items[?(@.metadata.labels.component == 'spark-master')].metadata.name}",
        timeout=300
    )
    logging.info("spark master is ready")
    
    logging.info("*** spark cluster created successfully")
    return res


def delete(owner=None):
    """
    Remove Apache Spark cluster from Kubernetes
    
    Args:
        owner: Owner reference (if present, uses delete by owner)
    
    Returns:
        Result message from deletion
    """
    logging.info("*** deleting spark cluster")
    
    if owner:
        # Delete via owner reference rebuild
        spec = kus.build("spark")
    else:
        # Delete via saved spec
        spec = cfg.get("state.spark.spec")
    
    if spec:
        res = kube.delete(spec)
        logging.info(f"deleted spark cluster: {res}")
        return res
    
    logging.warning("no spark spec found")
    return False


def patch(status, action, owner=None):
    """
    Handle update/patch of Spark component
    
    Args:
        status: Status object of the CRD
        action: 'create' or 'delete'
        owner: Owner reference
    """
    try:
        logging.info(f"*** handling {action} spark")
        
        if action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status, 'spark', 'on')
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status, 'spark', 'off')
        
        logging.info(msg)
    
    except Exception as e:
        logging.error(f'*** failed to {action} spark: {e}')
        operator_util.patch_operator_status(status, 'spark', 'error')
        raise


def configure_spark(data):
    """
    Post-deployment configuration for Spark cluster
    
    Tasks:
    - Verify master-worker connectivity
    - Create event log directory if using local storage
    - Configure History Server event log scanning
    - Verify cluster health
    
    Args:
        data: Configuration data dictionary
    """
    logging.info("configuring spark cluster")
    
    try:
        # 1. Verify Spark Master is accessible
        namespace = data['namespace']
        master_url = f"spark://spark-master:7077"
        
        logging.info(f"verifying spark master at {master_url}")
        
        # 2. Check worker registration (via master web UI)
        expected_workers = data['worker_replicas']
        max_retries = 12
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                # Query master web UI for registered workers
                result = subprocess.run(
                    ['kubectl', 'exec', '-n', namespace, 
                     'spark-master-0', '--',
                     'curl', '-s', 'http://localhost:8080/json/'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    import json
                    master_info = json.loads(result.stdout)
                    active_workers = len(master_info.get('workers', []))
                    
                    logging.info(f"spark master has {active_workers}/{expected_workers} workers registered")
                    
                    if active_workers >= expected_workers:
                        logging.info("all spark workers registered successfully")
                        break
                else:
                    logging.warning(f"failed to query spark master: {result.stderr}")
            
            except Exception as e:
                logging.warning(f"attempt {attempt+1}/{max_retries} to verify workers failed: {e}")
            
            if attempt < max_retries - 1:
                logging.info(f"waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
        
        # 3. Create event log directory if using local storage
        if data['event_log_enabled'] and data['history_enabled']:
            logging.info("ensuring spark event log directory exists")
            
            # Create directory on history server pod
            result = subprocess.run(
                ['kubectl', 'exec', '-n', namespace,
                 'deployment/spark-history', '--',
                 'mkdir', '-p', data['event_log_dir']],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logging.info(f"event log directory {data['event_log_dir']} created")
            else:
                logging.warning(f"failed to create event log directory: {result.stderr}")
        
        # 4. Log cluster configuration summary
        logging.info("spark cluster configuration:")
        logging.info(f"  - Master: {data['master_replicas']} replica(s)")
        logging.info(f"  - Workers: {data['worker_replicas']} replica(s)")
        logging.info(f"  - Worker cores: {data['worker_cores']} per worker")
        logging.info(f"  - Worker memory: {data['worker_memory']} per worker")
        logging.info(f"  - History Server: {'enabled' if data['history_enabled'] else 'disabled'}")
        logging.info(f"  - High Availability: {'enabled' if data['ha_enabled'] else 'disabled'}")
        
        logging.info("spark cluster configuration completed")
    
    except Exception as e:
        logging.error(f"error during spark post-configuration: {e}")
        # Don't raise - allow cluster to be usable even if post-config fails
        logging.warning("spark cluster is deployed but post-configuration had issues")


def scale_workers(replicas):
    """
    Scale Spark workers to specified number of replicas
    
    Args:
        replicas: Target number of worker replicas
    
    Returns:
        Result message
    """
    logging.info(f"scaling spark workers to {replicas} replicas")
    
    namespace = cfg.get('nuvolaris.namespace', default='nuvolaris')
    
    result = subprocess.run(
        ['kubectl', 'scale', 'statefulset', 'spark-worker',
         '-n', namespace,
         f'--replicas={replicas}'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        logging.info(f"spark workers scaled to {replicas}")
        return f"scaled to {replicas} workers"
    else:
        raise Exception(f"failed to scale workers: {result.stderr}")


def get_cluster_info():
    """
    Get current Spark cluster information
    
    Returns:
        Dict with cluster status and metrics
    """
    namespace = cfg.get('nuvolaris.namespace', default='nuvolaris')
    
    try:
        # Get master info
        result = subprocess.run(
            ['kubectl', 'exec', '-n', namespace,
             'spark-master-0', '--',
             'curl', '-s', 'http://localhost:8080/json/'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
        else:
            return {"error": "failed to get cluster info"}
    
    except Exception as e:
        logging.error(f"error getting cluster info: {e}")
        return {"error": str(e)}


# ==================== SparkJob CRD Handlers ====================

@kopf.on.create('nuvolaris.org', 'v1', 'sparkjobs')
def create_sparkjob(spec, name, namespace, status, **kwargs):
    """
    Handle SparkJob creation - submit Spark application to cluster
    
    Args:
        spec: SparkJob specification from CRD
        name: SparkJob resource name
        namespace: Kubernetes namespace
        status: Status object to update
        **kwargs: Additional kopf arguments
    
    Returns:
        Status dict with job information
    """
    logging.info(f"*** creating SparkJob {name} in namespace {namespace}")
    
    try:
        # 1. Validate SparkJob specification
        job_config = _validate_sparkjob_spec(spec, name)
        
        # 2. Create Kubernetes Job for Spark driver
        driver_job = _create_spark_driver_job(job_config, name, namespace)
        
        # 3. Submit job to cluster
        result = kube.apply(driver_job)
        
        # 4. Get application ID and update status
        app_id = _get_spark_application_id(name, namespace)
        
        # 5. Build success status
        status_dict = _build_sparkjob_status('Running', 'SparkJob submitted to cluster', 
                                           app_id=app_id, start_time=True, existing_status=status)
        
        # Add additional fields  
        status_dict['driverPod'] = f"{name}-driver"
        status_dict['sparkUI'] = {
            'driverUI': f"http://{name}-driver:4040",
            'historyUI': f"http://spark-history:18080"
        }
        
        logging.info(f"SparkJob {name} submitted successfully with application ID: {app_id}")
        return status_dict
        
    except Exception as e:
        logging.error(f"failed to create SparkJob {name}: {e}")
        status_dict = _build_sparkjob_status('Failed', f'Job creation failed: {str(e)}', existing_status=status)
        return status_dict


@kopf.on.delete('nuvolaris.org', 'v1', 'sparkjobs')
def delete_sparkjob(spec, name, namespace, **kwargs):
    """
    Handle SparkJob deletion - cleanup driver job and associated resources
    
    Args:
        spec: SparkJob specification from CRD
        name: SparkJob resource name  
        namespace: Kubernetes namespace
        **kwargs: Additional kopf arguments
    """
    logging.info(f"*** deleting SparkJob {name} in namespace {namespace}")
    
    try:
        # 1. Delete the Kubernetes Job for Spark driver
        delete_job_spec = {
            'apiVersion': 'batch/v1',
            'kind': 'Job', 
            'metadata': {
                'name': f"{name}-driver",
                'namespace': namespace
            }
        }
        
        result = kube.delete(delete_job_spec)
        
        # 2. Kill running Spark application if still active
        app_id = spec.get('status', {}).get('applicationId')
        if app_id:
            _kill_spark_application(app_id, namespace)
        
        logging.info(f"SparkJob {name} deleted successfully")
        return {'message': f'SparkJob {name} deleted'}
        
    except Exception as e:
        logging.error(f"failed to delete SparkJob {name}: {e}")
        # Don't raise - allow deletion to proceed even if cleanup fails
        return {'message': f'SparkJob {name} deletion completed with warnings: {e}'}


@kopf.on.field('nuvolaris.org', 'v1', 'sparkjobs', field='spec')
def update_sparkjob(old, new, name, namespace, **kwargs):
    """
    Handle SparkJob specification updates
    
    Args:
        old: Previous specification
        new: New specification  
        name: SparkJob resource name
        namespace: Kubernetes namespace
        **kwargs: Additional kopf arguments
    """
    logging.info(f"*** updating SparkJob {name} in namespace {namespace}")
    
    # For now, SparkJob updates are not supported - would need to restart the job
    logging.warning(f"SparkJob {name} specification changed, but updates are not supported")
    logging.info("To apply changes, delete and recreate the SparkJob")
    
    return {'message': 'SparkJob updates not supported - delete and recreate to apply changes'}


def _validate_sparkjob_spec(spec, job_name):
    """
    Validate and normalize SparkJob specification
    
    Args:
        spec: Raw SparkJob spec from CRD
        job_name: Name of the SparkJob resource
    
    Returns:
        Dict with validated and normalized job configuration
    
    Raises:
        ValueError: If specification is invalid
    """
    # Default configuration
    config = {
        'name': job_name,
        'application': {},
        'spark': {
            'master': 'spark://spark-master:7077',
            'conf': {},
            'driver': {
                'cores': 0.5,
                'memory': '512m',
                'serviceAccount': 'spark'
            },
            'executor': {
                'instances': 2,
                'cores': 1, 
                'memory': '1g'
            }
        },
        'execution': {
            'restartPolicy': 'OnFailure',
            'timeout': 3600,
            'backoffLimit': 3
        },
        'dependencies': {
            'jars': [],
            'files': [],
            'pyFiles': []
        },
        'monitoring': {
            'enabled': True,
            'eventLog': True,
            'historyServer': True
        }
    }
    
    # Merge user specification
    def merge_dict(target, source):
        for key, value in source.items():
            if isinstance(value, dict) and key in target:
                merge_dict(target[key], value)
            else:
                target[key] = value
    
    if spec:
        merge_dict(config, spec)
    
    # Validate required fields
    if not config['application'].get('mainApplicationFile'):
        raise ValueError("application.mainApplicationFile is required")
    
    # Validate source configuration
    app_source = config['application'].get('source', {})
    source_type = app_source.get('type', 'url')
    
    if source_type == 'configMap' and not app_source.get('configMapRef'):
        raise ValueError("application.source.configMapRef is required for configMap source type")
    elif source_type == 'secret' and not app_source.get('secretRef'):
        raise ValueError("application.source.secretRef is required for secret source type")
    elif source_type == 'url' and not app_source.get('url'):
        raise ValueError("application.source.url is required for url source type")
    elif source_type == 'inline' and not app_source.get('content'):
        raise ValueError("application.source.content is required for inline source type")
    
    logging.info(f"validated SparkJob configuration for {job_name}")
    return config


def _convert_k8s_memory_to_jvm(k8s_memory):
    """
    Convert Kubernetes memory format (like '1Gi') to JVM format (like '1g')
    """
    if k8s_memory.endswith('Gi'):
        return k8s_memory[:-2] + 'g'
    elif k8s_memory.endswith('Mi'):
        return k8s_memory[:-2] + 'm' 
    elif k8s_memory.endswith('Ki'):
        return k8s_memory[:-2] + 'k'
    else:
        # Already in JVM format or simple number
        return k8s_memory


def _create_spark_driver_job(job_config, job_name, namespace):
    """
    Create Kubernetes Job specification for Spark driver
    
    Args:
        job_config: Validated SparkJob configuration
        job_name: Name of the SparkJob resource
        namespace: Kubernetes namespace
    
    Returns:
        Dict with Kubernetes Job specification
    """
    app = job_config['application']
    spark = job_config['spark']
    execution = job_config['execution']
    deps = job_config['dependencies']
    monitoring = job_config['monitoring']
    
    # Build spark-submit command with JVM-compatible memory formats
    jvm_driver_memory = _convert_k8s_memory_to_jvm(spark['driver']['memory'])
    jvm_executor_memory = _convert_k8s_memory_to_jvm(spark['executor']['memory'])
    
    submit_cmd = [
        '/opt/spark/bin/spark-submit',
        '--master', spark['master'],
        '--name', job_name,
        '--driver-cores', str(spark['driver']['cores']),
        '--driver-memory', jvm_driver_memory,
        '--num-executors', str(spark['executor']['instances']),
        '--executor-cores', str(spark['executor']['cores']), 
        '--executor-memory', jvm_executor_memory,
        '--deploy-mode', 'client'  # Client mode for Kubernetes Jobs
    ]
    
    # Add Spark configuration
    for key, value in spark['conf'].items():
        submit_cmd.extend(['--conf', f'{key}={value}'])
    
    # Add event logging configuration if enabled
    if monitoring['eventLog']:
        submit_cmd.extend([
            '--conf', 'spark.eventLog.enabled=true',
            '--conf', 'spark.eventLog.dir=/tmp/spark-events'
        ])
    
    # Add dependencies
    if deps['jars']:
        submit_cmd.extend(['--jars', ','.join(deps['jars'])])
    if deps['files']:
        submit_cmd.extend(['--files', ','.join(deps['files'])])
    if deps['pyFiles']:
        submit_cmd.extend(['--py-files', ','.join(deps['pyFiles'])])
    
    # Add main class if specified (for Java/Scala) - MUST come before JAR file
    if app.get('mainClass'):
        submit_cmd.extend(['--class', app['mainClass']])
    
    # Add main application file
    submit_cmd.append(app['mainApplicationFile'])
    
    # Add application arguments
    if app.get('arguments'):
        submit_cmd.extend(app['arguments'])
    
    # Create Job specification
    job_spec = {
        'apiVersion': 'batch/v1',
        'kind': 'Job',
        'metadata': {
            'name': f"{job_name}-driver",
            'namespace': namespace,
            'labels': {
                'app': 'spark',
                'component': 'driver',
                'sparkjob': job_name
            }
        },
        'spec': {
            'backoffLimit': execution['backoffLimit'],
            'activeDeadlineSeconds': execution['timeout'],
            'template': {
                'metadata': {
                    'labels': {
                        'app': 'spark',
                        'component': 'driver', 
                        'sparkjob': job_name
                    }
                },
                'spec': {
                    'restartPolicy': execution['restartPolicy'],
                    'serviceAccountName': spark['driver']['serviceAccount'],
                    'containers': [{
                        'name': 'spark-driver',
                        'image': cfg.get('spark.image', defval='apache/spark:3.5.0'),
                        'command': submit_cmd,
                        'env': [
                            {'name': 'SPARK_USER', 'value': 'spark'},
                            {'name': 'SPARK_APPLICATION_ID', 'value': job_name}
                        ],
                        'resources': {
                            'requests': {
                                'cpu': f"{int(spark['driver']['cores']) * 100}m",
                                'memory': spark['driver']['memory']
                            },
                            'limits': {
                                'cpu': f"{int(spark['driver']['cores']) * 100}m",
                                'memory': spark['driver']['memory']
                            }
                        },
                        'volumeMounts': []
                    }],
                    'volumes': []
                }
            }
        }
    }
    
    # Add event log volume if enabled
    if monitoring['eventLog'] and monitoring['historyServer']:
        job_spec['spec']['template']['spec']['containers'][0]['volumeMounts'].append({
            'name': 'spark-events',
            'mountPath': '/tmp/spark-events'
        })
        job_spec['spec']['template']['spec']['volumes'].append({
            'name': 'spark-events',
            'persistentVolumeClaim': {
                'claimName': 'spark-history-pvc'
            }
        })
    
    return job_spec


def _build_sparkjob_status(phase, message, app_id=None, start_time=False, existing_status=None):
    """
    Build SparkJob status dictionary
    
    Args:
        phase: Job phase (Pending, Running, Succeeded, Failed)
        message: Status message
        app_id: Spark application ID (optional)
        start_time: Whether to set start time (optional)
        existing_status: Existing status to update (optional)
        
    Returns:
        Dictionary with status fields
    """
    import datetime
    
    # Start with existing status or empty dict
    status_dict = existing_status.copy() if existing_status else {}
    
    # Set basic fields
    status_dict['phase'] = phase
    status_dict['message'] = message
    
    # Initialize conditions if not present
    if 'conditions' not in status_dict:
        status_dict['conditions'] = []
    
    # Add/update condition
    condition = {
        'type': 'Ready',
        'status': 'True' if phase == 'Running' else 'False',
        'lastTransitionTime': datetime.datetime.utcnow().isoformat() + 'Z',
        'reason': phase,
        'message': message
    }
    
    # Remove old conditions of same type and add new one
    status_dict['conditions'] = [c for c in status_dict['conditions'] if c['type'] != 'Ready']
    status_dict['conditions'].append(condition)
    
    # Add application ID if provided
    if app_id:
        status_dict['applicationId'] = app_id
    
    # Add start time if requested
    if start_time:
        status_dict['startTime'] = datetime.datetime.utcnow().isoformat() + 'Z'
    
    # Add completion time if job is finished
    if phase in ['Succeeded', 'Failed']:
        status_dict['completionTime'] = datetime.datetime.utcnow().isoformat() + 'Z'
        
    return status_dict


def _get_spark_application_id(job_name, namespace):
    """
    Get Spark application ID from driver pod logs
    
    Args:
        job_name: SparkJob resource name
        namespace: Kubernetes namespace
    
    Returns:
        String with application ID or None if not found
    """
    try:
        # Wait a bit for the driver to start
        time.sleep(5)
        
        # Get logs from driver pod
        result = subprocess.run(
            ['kubectl', 'logs', '-n', namespace,
             f'job/{job_name}-driver',
             '--tail=100'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # Parse application ID from logs (format: application_1234567890_0001)
            lines = result.stdout.split('\n')
            for line in lines:
                if 'Submitted application' in line and 'application_' in line:
                    # Extract application ID
                    parts = line.split()
                    for part in parts:
                        if part.startswith('application_'):
                            return part
        
        # If not found in initial logs, return generated ID
        return f"application_{int(time.time())}_{job_name}"
        
    except Exception as e:
        logging.warning(f"could not determine application ID for {job_name}: {e}")
        return f"application_{int(time.time())}_{job_name}"


def _kill_spark_application(app_id, namespace):
    """
    Kill running Spark application
    
    Args:
        app_id: Spark application ID
        namespace: Kubernetes namespace
    """
    try:
        # Try to kill via Spark master
        result = subprocess.run(
            ['kubectl', 'exec', '-n', namespace,
             'spark-master-0', '--',
             'curl', '-X', 'POST',
             f'http://localhost:8080/app/kill/?id={app_id}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logging.info(f"killed Spark application {app_id}")
        else:
            logging.warning(f"failed to kill application {app_id}: {result.stderr}")
            
    except Exception as e:
        logging.warning(f"error killing Spark application {app_id}: {e}")
