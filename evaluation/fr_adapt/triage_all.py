import click
import os
import subprocess

PWD = os.path.dirname(os.path.abspath(__file__))

TRIAGE_ONE = os.path.join(PWD, "triage.py")

@click.command()
@click.option("--root", "-i", type=str, required=True)
@click.option("--output", "-o", type=str, default="triage")
@click.option("--parallel", "-j", type=int, default=10)
def main(root, output, parallel):
    for i in range(1, 11):
        print(f"Triage {i} / 10")
        cmd = [
            "python",
            TRIAGE_ONE,
            "--afl-root",
            os.path.join(root, str(i)),
            "--output",
            os.path.join(output, str(i)),
            "--parallel",
            str(parallel),
            "-c"
        ]
        subprocess.run(cmd)

if __name__ == "__main__":
    main()