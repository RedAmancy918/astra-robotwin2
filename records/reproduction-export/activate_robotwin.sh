# Source this file: source /mnt/data/yjh/activate_robotwin.sh
source /media/aaa/miniconda3/etc/profile.d/conda.sh
conda activate /mnt/data/yjh/conda_envs/robotwin
export CUDA_HOME=/mnt/data/yjh/conda_envs/robotwin
export CUDA_PATH=/mnt/data/yjh/conda_envs/robotwin
export TORCH_CUDA_ARCH_LIST="12.0"
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
export PYTHONNOUSERSITE=1
cd /mnt/data/yjh/RoboTwin
