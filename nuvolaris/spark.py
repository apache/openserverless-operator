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
import nuvolaris.operator_util as operator_util
import time
import subprocess


def get_spark_config_data():
    """
    Collect Spark configuration from CRD spec
    
    Returns:
        Dict with complete Spark configuration
    """
    namespace = cfg.get('nuvolaris.namespace', default='nuvolaris')
    
    data = {
        # Basic configuration
        "name": "spark",
        "namespace": namespace,
        
        # Spark images
        "spark_image": cfg.get('spark.image', default='apache/spark:3.5.0'),
        "spark_version": cfg.get('spark.version', default='3.5.0'),
        
        # Master configuration
        "master_replicas": cfg.get('spark.master.replicas', default=1),
        "master_memory": cfg.get('spark.master.memory', default='1g'),
        "master_cpu": cfg.get('spark.master.cpu', default='1000m'),
        "master_port": cfg.get('spark.master.port', default=7077),
        "master_webui_port": cfg.get('spark.master.webui-port', default=8080),
        
        # Worker configuration
        "worker_replicas": cfg.get('spark.worker.replicas', default=2),
        "worker_memory": cfg.get('spark.worker.memory', default='2g'),
        "worker_cpu": cfg.get('spark.worker.cpu', default='2000m'),
        "worker_cores": cfg.get('spark.worker.cores', default=2),
        "worker_webui_port": cfg.get('spark.worker.webui-port', default=8081),
        
        # History Server configuration
        "history_enabled": cfg.get('spark.history-server.enabled', default=True),
        "history_port": cfg.get('spark.history-server.port', default=18080),
        "history_volume_size": cfg.get('spark.history-server.volume-size', default=10),
        
        # Storage configuration
        "event_log_enabled": cfg.get('spark.event-log.enabled', default=True),
        "event_log_dir": cfg.get('spark.event-log.dir', default='/tmp/spark-events'),
        
        # High Availability (optional)
        "ha_enabled": cfg.get('spark.ha.enabled', default=False),
        "ha_zookeeper_url": cfg.get('spark.ha.zookeeper-url', default=''),
        
        # Affinity and tolerations
        "affinity": cfg.get('affinity', default=False),
        "affinity_core_node_label": cfg.get('affinity-core-node-label', default='nuvolaris'),
        "tolerations": cfg.get('tolerations', default=False),
        
        # Security
        "spark_user": cfg.get('spark.user', default='spark'),
        "spark_uid": cfg.get('spark.uid', default=185),
    }
    
    return data


def create(owner=None):
    """
    Deploy Apache Spark cluster on Kubernetes
    
    Creates:
    - Spark Master (StatefulSet with optional HA)
    - Spark Workers (StatefulSet)
    - Spark History Server (Deployment with PVC)
    - Required Services
    - ConfigMaps for configuration
    
    Args:
        owner: Owner reference for garbage collection
    
    Returns:
        Result message from deployment
    """
    logging.info("*** creating spark cluster")
    
    # 1. Collect configuration
    data = get_spark_config_data()
    
    # 2. Define templates to apply
    tplp = [
        "00-spark-rbac.yaml",           # ServiceAccount, Role, RoleBinding
        "01-spark-configmap.yaml",      # Spark configuration
        "02-spark-history-pvc.yaml",    # PVC for History Server
        "03-spark-master-sts.yaml",     # Master StatefulSet
        "04-spark-master-svc.yaml",     # Master Service
        "05-spark-worker-sts.yaml",     # Worker StatefulSet
        "06-spark-worker-svc.yaml",     # Worker Service (headless)
    ]
    
    # Add History Server if enabled
    if data['history_enabled']:
        tplp.append("07-spark-history-dep.yaml")
        tplp.append("08-spark-history-svc.yaml")
    
    # 3. Generate kustomization with patches
    kust = kus.patchTemplates("spark", tplp, data)
    
    # 4. Additional Jinja2 templates
    templates = []
    if data['affinity']:
        templates.append('affinity-tolerance-sts-core-attach.yaml')
    
    # 5. Build complete specification
    spec = kus.kustom_list("spark", kust, templates=templates, data=data)
    
    # 6. Apply owner reference for garbage collection
    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        # Save spec for delete without owner
        cfg.put("state.spark.spec", spec)
    
    # 7. Deploy to Kubernetes
    res = kube.apply(spec)
    logging.info("spark manifests applied")
    
    # 8. Wait for Master to be ready
    logging.info("waiting for spark master to be ready...")
    util.wait_for_pod_ready(
        "{.items[?(@.metadata.labels.component == 'spark-master')].metadata.name}",
        timeout=300
    )
    logging.info("spark master is ready")
    
    # 9. Wait for Workers to be ready
    logging.info("waiting for spark workers to be ready...")
    time.sleep(10)  # Give workers time to start connecting
    util.wait_for_pod_ready(
        "{.items[?(@.metadata.labels.component == 'spark-worker')].metadata.name}",
        timeout=300
    )
    logging.info("spark workers are ready")
    
    # 10. Wait for History Server if enabled
    if data['history_enabled']:
        logging.info("waiting for spark history server to be ready...")
        util.wait_for_pod_ready(
            "{.items[?(@.metadata.labels.component == 'spark-history')].metadata.name}",
            timeout=180
        )
        logging.info("spark history server is ready")
    
    # 11. Post-configuration
    configure_spark(data)
    
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
