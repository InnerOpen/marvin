// Settings → Workers → "Run a worker": the commands for each way to run one, with this installation's API address and workspace filled in.
// A worker authenticates with a token pinned to the workspace (MARVIN_USER_TOKEN), never one pasted here: the commands only name it.
// The full guide, with the Kubernetes manifests, is docs/deploy.md in the marvin-worker repository.

export interface CommandBlock {
  /** what this command does, one line */
  label: string;
  code: string;
}

export interface RunOption {
  id: "process" | "docker" | "podman" | "kubernetes";
  title: string;
  /** when to pick it */
  blurb: string;
  blocks: CommandBlock[];
}

export interface RunGuide {
  /** the same for every option: make the record types, make a token */
  first: CommandBlock[];
  options: RunOption[];
}

const IMAGE = "my-worker";

/** The commands for this Marvin and workspace. `workspaceSlug` is a placeholder when the page could not read it. */
export function runGuide(apiUrl: string, workspaceSlug: string): RunGuide {
  const env = `export MARVIN_API_URL=${apiUrl}\nexport MARVIN_USER_TOKEN=<the token above>`;
  const dockerRun = (cli: "docker" | "podman") =>
    `${cli} run -d --name my-runner --restart unless-stopped \\\n  -e MARVIN_API_URL=${apiUrl} -e MARVIN_USER_TOKEN -e WORKER_NAME=my-runner \\\n  ${IMAGE} python -m marvin_worker work`;
  const secret = (cli: "kubectl" | "oc") => `${cli} create secret generic marvin-worker --from-literal=MARVIN_USER_TOKEN=<the token above>`;

  return {
    first: [
      { label: "1. Add the record types workers use (once per workspace)", code: "marvin platform workers setup" },
      { label: "2. Make a token that can reach only this workspace", code: `marvin user tokens create --name worker --pin ${workspaceSlug}` },
    ],
    options: [
      {
        id: "process",
        title: "A process on a machine",
        blurb: "A runner on a machine that has the tools (ffmpeg, say). Nothing else to install. Keep it up with systemd or tmux.",
        blocks: [
          { label: "Install the worker", code: "git clone https://github.com/InnerOpen/marvin-worker && cd marvin-worker\npip install ." },
          { label: "Start a runner: it takes the jobs it can do", code: `${env}\nexport WORKER_NAME=my-runner\npython -m marvin_worker work` },
          { label: "Or a dispatcher: it starts a container (or Job) for each job", code: `${env}\npython -m marvin_worker dispatch` },
        ],
      },
      {
        id: "docker",
        title: "Docker",
        blurb: "A runner that is always on, or a dispatcher that starts a fresh container per job, which ends with the job.",
        blocks: [
          { label: "Build the base image, then your own from it (see the guide)", code: "docker build -f docker/Dockerfile -t marvin-worker-base .\ndocker build -t my-worker ./my-pack" },
          { label: "A runner, always on (-e with no value copies the token from your shell)", code: `export MARVIN_USER_TOKEN=<the token above>\n${dockerRun("docker")}` },
          { label: "Or a dispatcher on the Docker host, with a job-kind record: mode docker and the image", code: `${env}\npython -m marvin_worker dispatch` },
        ],
      },
      {
        id: "podman",
        title: "Podman",
        blurb: "The same as Docker (rootless is fine). Tell the dispatcher to use podman.",
        blocks: [
          { label: "A runner, always on", code: `export MARVIN_USER_TOKEN=<the token above>\n${dockerRun("podman")}` },
          { label: "A dispatcher that starts a Podman container per job", code: `${env}\nexport WORKER_CONTAINER_CLI=podman\npython -m marvin_worker dispatch` },
        ],
      },
      {
        id: "kubernetes",
        title: "Kubernetes or OpenShift",
        blurb: "A dispatcher that makes a Job per run, or a runner as a Deployment. The token lives in a Secret. Not yet run on a real cluster.",
        blocks: [
          { label: "Kubernetes: the token as a Secret", code: secret("kubectl") },
          { label: "OpenShift: the same with oc", code: secret("oc") },
          { label: "Then apply the dispatcher or runner manifests, with the Role it needs (docs/deploy.md)", code: "kubectl apply -f dispatcher.yaml    # or: oc apply -f dispatcher.yaml" },
        ],
      },
    ],
  };
}
