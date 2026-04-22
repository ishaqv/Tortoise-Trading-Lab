import os

import googleapiclient.discovery


def manage_vm(request):
    """
        Starts or stops a Google Cloud VM instance based on environment variables.

        Required environment variables:
            - GCP_PROJECT: The Google Cloud project ID.
            - ZONE: The zone in which the VM instance resides (e.g., "asia-south1-c").
            - INSTANCE: The name of the VM instance (e.g., "nse-trader-vm").
            - ACTION: The action to perform — "start" or "stop".

        Args:
            request: (Optional) HTTP request object if used as a Cloud Function.

        Returns:
            str: A message indicating whether the VM was started or stopped,
                 or an error message for invalid action.
        """

    project = os.environ.get('GCP_PROJECT')
    zone = os.environ.get('ZONE')  # e.g. asia-south1-c
    instance = os.environ.get('INSTANCE')  # e.g. "nse-trader-vm"
    action = os.environ.get('ACTION')  # "start" or "stop"

    compute = googleapiclient.discovery.build('compute', 'v1')

    if action == 'start':
        compute.instances().start(project=project, zone=zone, instance=instance).execute()
        return f"Started {instance}"
    elif action == 'stop':
        compute.instances().stop(project=project, zone=zone, instance=instance).execute()
        return f"Stopped {instance}"
    else:
        return "Invalid action"
