# Distribution and provenance evidence

CI results describe checks performed on a specific source revision. They do
not by themselves establish that a package or browser bundle was published.

For a published distribution, inspect the package registry and the artifact
actually retrieved from it. Record the package name, version, source revision
and the artifact's cryptographic digest. Compare the retrieved bytes with the
intended artifact. Where an attestation is available, verify its signature,
subject digest and source identity using the relevant registry's documented
verification process. An absent or unverifiable attestation is not evidence
of provenance.

The Python and npm packages and any separately distributed browser bundle
are distinct artifacts. Check each distribution that matters to the intended
use; successful verification of one does not establish the contents or
availability of another.
