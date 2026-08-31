# TODO

The template's post-generation hook created the repository, turned immutable
releases on and left merge commits as the only way to land a pull request. What
is left needs a human. Each step assumes the ones above it are done.

- [ ] Register the trusted publisher on PyPI, so the `pypi` job can
  `uv publish` without an API token. Add a pending publisher for the project
  `turnstile-solver`, and fill it in with:

  - Owner: `eggplants`
  - Repository: `turnstile-solver`
  - Workflow: `release.yml`
  - Environment: `pypi`

  [What the OIDC handshake is doing][oidc].

- [ ] Cut the first release by tagging `master`. `release.yml` creates the
  GitHub release, then publishes to PyPI.

  ```bash
  git tag v0.0.0
  git push origin v0.0.0
  ```

[oidc]: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-pypi

- [ ] Publish the repository. Pages, PyPI trusted publishing and the README
  badges all assume it is public.

  ```bash
  gh repo edit eggplants/turnstile-solver \
    --visibility public --accept-visibility-change-consequences
  ```

- [ ] Turn GitHub Pages on, serving `/` of the `gh-pages` branch that
  `docs.yml` pushes on every commit to `master`, over HTTPS only. Wait for the
  first `docs` run to land; the branch has to exist first.

  ```bash
  gh api -X POST '/repos/eggplants/turnstile-solver/pages' \
    -f 'source[branch]=gh-pages' -f 'source[path]=/' -F https_enforced=true
  ```
