import hashlib,hmac,tempfile,unittest
from pathlib import Path
from webhook import verify,accept
class T(unittest.TestCase):
 def test_signature(self):
  b=b'{}'; s=b'secret'; sig='sha256='+hmac.new(s,b,hashlib.sha256).hexdigest(); self.assertTrue(verify(s,b,sig)); self.assertFalse(verify(s,b,sig+'x'))
 def test_dedup(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'e.db'; self.assertTrue(accept(p,'abc','check_run','o/r',b'{}')); self.assertFalse(accept(p,'abc','check_run','o/r',b'{}'))
if __name__=='__main__': unittest.main()
