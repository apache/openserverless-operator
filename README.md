# Apache OpenServerless Operator

In this readme there are informations for developer, please refer to the [website](https://openserverless.apache.org) for more informations.


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

## How to build and use an operator image

Ensure you have satified the prerequisites.

Note you need write access to a github repository repository.

The task build will commit and push all your changes and then build the operator from the public sources in your local k3s.


