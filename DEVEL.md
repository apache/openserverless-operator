# How to do develoment with the operator

The operator is a collection of modules managed with ops. 
The operator itself is an ops plugin to invoke its functions from the command line:

To work with it, install ops and clone the code:

```
curl -sL bit.ly/get-ops | bash
git clone https://github.com/apache/openserverless --recurse-submodules
cd openserverless
```

You can then launch IPython to work with it

```
ops op cli
```

To be able to work with the operator you need a Kubernetes cluster and a Working configuration. 
Create one with kind:

```
ops op clu kind create
```

Create a full config skipping the actual launch of the operator

```
ops -config SKIP_OPERATOR_LAUNCH=1
ops config slim
ops setup kubernetes create
```
