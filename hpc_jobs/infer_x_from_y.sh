#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=4:00:00
#SBATCH --mem=12GB
#SBATCH --job-name=massive_infer_x_from_y_node_0_h_para_standard_h_init_random
#SBATCH --mail-type=END
#SBATCH --mail-user=yw1225@nyu.edu
#SBATCH --output=slurm_%j.out

module purge
module load python3/intel/3.5.3
# module load tensorflow/python3.5/1.1.0
module load tensorflow/python3.5/1.0.1
#SBATCH --gres=gpu:1

JOBNAME=massive_infer_x_from_y_node_0_h_para_standard_h_init_random
RUNDIR=$SCRATCH/runs/$JOBNAME-${SLURM_JOB_ID/.*}
SOURCEDIR=~/projects/DCM_RNN/dcm_rnn
OUTPUTDIR=$SCRATCH/results/DCM_RNN/$JOBNAME/${SLURM_JOB_ID/.*}
#SBATCH --gres=gpu:1


mkdir -p $RUNDIR
mkdir -p $OUTPUTDIR
export PYTHONPATH=$PYTHONPATH:$SOURCEDIR
echo $PYTHONPATH
cd $RUNDIR

python3 ~/projects/DCM_RNN/experiments/infer_x_from_y/experiment_main.py


# leave a blank line at the end