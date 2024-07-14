# Warning: DO NOT USE YET - migration in Progress 
Please do not try to use this code until this notice is removed.

# Apache OpenServerless Operator

In this readme there are informations for developers. 

We describe how to build and test the operator in our development environment

Please refer to the [website](https://openserverless.apache.org) for user informations.

## How to build and use an operator image

Ensure you have satified the prerequisites below. Most notably, you need to use our development virtual machine and you need write access to a github repository repository.

Once you have satisfied the prerequisites, you can build an image you can use in the development machine.

Build an image with `task build`. 

Please note the it will build the image locally and push in an internal registry, even if it is name is `ghcr.io/${GITHUB_USER}/openserverless-operator`.

To be able to build, the task `build` will commit and push all your changes and then build the operator from the public sources in your local k3s.

It will also generate

You can then deploy it with `task deploy`.

Once you have finished  with development you can create a publici image with `task publish` that will publish the tag and trigger a creation of the image.

## Prerequisites

1. Please setup and use a development VM [as described here](https://github.com/apache/openserverless)

2. With VSCode, access to the development VM, open the workspace `openserverless/openserverless.code-orkspace` and then open a terminal with `operator` subproject e enabling the nix enviroment with direnv (the vm provides those). 

3. Create a fork of `githbub.com/apache/openserverless-operator`

4. Copy .env.dist in .env and put your github username in it

5. Since the build requires you push your sources in your repo, you need the credentials to access it. The fastest way is to [create a personal token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) 

6. Now setup a remote to access your repo and set it as your default upstream branch.

```
git remote add fork https://<GITHUB_USERNAME>:<GITHUB_TOKEN>@github.com/<GITHUB_USERNAME>/openserverless-operator
git branch -u https://github.com/<GITHUB_USERNAME>/openserverless-operator
```

That's it. Now you can use `task build` to build the image

