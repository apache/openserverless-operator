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

let
  nixpkgs = fetchTarball "https://github.com/NixOS/nixpkgs/tarball/nixos-23.11";
  pkgs = import nixpkgs { config = {}; overlays = []; };

  # 
  # Align the version of minio-client to the same used by openserverless operator if changed
  # and update also the sha256 value accordingly.
  #
  minio-client = pkgs.stdenv.mkDerivation rec {
    pname = "minio-client";
    version = "RELEASE.2023-03-23T20-03-04Z";
    src = pkgs.fetchurl {
      url = "https://dl.min.io/client/mc/release/linux-amd64/archive/mc.${version}";
      sha256 = "5de4aec1fc6c6608723a1d6da988350c876d5eb14538000ccb4d3a226199ab89";
    };
    phases = [ "unpackPhase" "installPhase" ];
    unpackPhase = ''
      runHook preUnpack
      mkdir -p $out
      cp $src $out/mc.${version}
      runHook postUnpack
    '';
    installPhase = ''
      mkdir -p $out/bin
      install -m755 $out/mc.${version} $out/bin/mc
    '';    
  };

  #
  # Openwhisk wsk CLI it is still required
  #
  wsk = pkgs.stdenv.mkDerivation rec {
    pname = "wsk";
    version = "1.2.0";

    src = pkgs.fetchurl {
      url = "https://github.com/apache/openwhisk-cli/releases/download/${version}/OpenWhisk_CLI-${version}-linux-amd64.tgz";
      sha256 = "c404ac124b7f98c49d293c9abae28740283ce2615248690e7652a94648780820";
    };

    phases = [ "unpackPhase" "installPhase" ];

    unpackPhase = ''
      runHook preUnpack
      
      mkdir -p $out/tmp      
      cat $src| tar xzvf - -C $out/tmp

      runHook postUnpack
    '';

    installPhase = ''
      mkdir -p $out/bin
      install -m755 $out/tmp/wsk $out/bin/wsk
    ''; 

  };

in

pkgs.mkShellNoCC {
  packages = with pkgs; [
   python3
   kubernetes-helm
   poetry
   zip
   unzip
   minio-client
   wsk
   kustomize
  ];

}
