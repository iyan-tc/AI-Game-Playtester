import shutil
import subprocess
import tarfile

import pytest
from playtester.seal import seal


@pytest.mark.skipif(not shutil.which("openssl"),reason="OpenSSL required for encrypted fleet deployment")
def test_recipient_can_open_evidence(tmp_path):
    key,certificate=tmp_path/"key.pem",tmp_path/"cert.pem"
    config=tmp_path/"openssl.cnf"
    config.write_text("[req]\ndistinguished_name=dn\n[dn]\n",encoding="ascii")
    subprocess.run(["openssl","req","-config",str(config),"-x509","-newkey","rsa:2048","-nodes","-days","1","-subj","/CN=Fixture",
        "-keyout",str(key),"-out",str(certificate)],check=True,capture_output=True)
    source=tmp_path/"private"
    source.mkdir()
    value=b"synthetic private game memory"
    (source/"checkpoint").write_bytes(value)
    sealed,opened=tmp_path/"evidence.cms",tmp_path/"opened.tgz"
    seal(source,certificate,sealed)
    assert value not in sealed.read_bytes()
    subprocess.run(["openssl","cms","-decrypt","-binary","-inform","DER","-in",str(sealed),"-recip",str(certificate),
        "-inkey",str(key),"-out",str(opened)],check=True,capture_output=True)
    with tarfile.open(opened) as archive:
        assert archive.extractfile("run/checkpoint").read()==value
