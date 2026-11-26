"""Seal a private run directory with a recipient certificate before artifact upload."""
import argparse
import os
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory


def seal(source, certificate, output):
    if not source.is_dir() or output.exists():
        raise ValueError("Expected an evidence directory and a new archive destination")
    with TemporaryDirectory(dir=output.parent) as temporary:
        archive=Path(temporary)/"evidence.tar.gz"
        encrypted=Path(temporary)/"evidence.cms"
        with tarfile.open(archive,"w:gz") as tar:
            tar.add(source,arcname="run")
        subprocess.run(["openssl","cms","-encrypt","-binary","-aes-256-gcm","-outform","DER",
                        "-in",str(archive),"-out",str(encrypted),str(certificate)],check=True)
        os.replace(encrypted,output)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("certificate",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    seal(args.source,args.certificate,args.output)


if __name__=="__main__":
    main()

