Bootstrap: docker
From: kulhanek/deep-rl-pytorch:latest

%post
    mkdir /deep-rl-pytorch
    cd /deep-rl-pytorch
    git init
    git remote set-url origin https://github.com/jkulhanek/deep-rl-pytorch.git
    git pull origin master
    pip3 install .

%runscript
    echo "Container is ready!"