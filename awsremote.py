from __future__ import print_function

import boto.ec2.autoscale
from time import sleep
from datetime import datetime
import subprocess

def shellquote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"

#our timestamping function, accurate to milliseconds
#(remove [:-3] to display microseconds)
def GetTime():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
#the AWS instances
class Machine:
    def __init__(self,host):
        self.host = host
    def setup(self):
        print(GetTime(),'Connecting to',self.host)
        if subprocess.call(['./transfer_git.sh',self.host]) != 0:
          print(GetTime(),'Couldn\'t set up machine '+self.host)
          sys.exit(1)
    def execute(self,command):
        ssh_command = ['ssh','-i','daala.pem','-o',' StrictHostKeyChecking=no',command]
        
#the job slots we can fill
class Slot:
    def __init__(self, machine=None):
        self.machine = machine
        self.p = None
    def execute(self, work):
        self.work = work
        output_name = work.filename+'.'+str(work.quality)+'.ogv'
        if self.work.individual:
            input_path = '/mnt/media/'+self.work.filename
        else:
            input_path = '/mnt/media/'+self.work.set+'/'+self.work.filename
        print(GetTime(),'Encoding',work.filename,'with quality',work.quality,'on',self.machine.host)
        if self.machine is None:
            print(GetTime(),'No support for local execution.')
            sys.exit(1)
        else:
            self.p = subprocess.Popen(['ssh','-i','daala.pem','-o',' StrictHostKeyChecking=no',
                'ec2-user@'+self.machine.host,
                ('DAALA_ROOT=/home/ec2-user/daala/ x="'+str(work.quality)+'" CODEC="'+work.codec+'" EXTRA_OPTIONS="'+work.extra_options+
                    '" /home/ec2-user/rd_tool/metrics_gather.sh '+shellquote(input_path)
                ).encode("utf-8")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def busy(self):
        if self.p is None:
            return False
        elif self.p.poll() is None:
            return True
        else:
            return False
    def gather(self):
        (stdout, stderr) = self.p.communicate()
        self.work.raw = stdout
        self.work.parse()

def get_machines(num_instances_to_use, aws_group_name):
    machines = []
    #connect to AWS
    ec2 = boto.ec2.connect_to_region('us-west-2');
    autoscale = boto.ec2.autoscale.AutoScaleConnection();

    #how many machines are currently running?
    group = autoscale.get_all_groups(names=[aws_group_name])[0]
    num_instances = len(group.instances)
    print(GetTime(),'Number of instances online:',len(group.instances))

    #switch on more machines if we need them
    if num_instances < num_instances_to_use:
        print(GetTime(),'Launching instances...')
        autoscale.set_desired_capacity(aws_group_name,num_instances_to_use)

        #tell us status every few seconds
        group = None
        while num_instances < num_instances_to_use:
            group = autoscale.get_all_groups(names=[aws_group_name])[0]
            num_instances = len(group.instances)
            print(GetTime(),'Number of instances online:',len(group.instances))
            sleep(3)

    #grab instance IDs
    instance_ids = [i.instance_id for i in group.instances]
    print(GetTime(),"These instances are online:",instance_ids)

    instances = ec2.get_only_instances(instance_ids)
    for instance in instances:
        print(GetTime(),'Waiting for instance',instance.id,'to boot...')
        while 1:
            instance.update()
            if instance.state == 'running':
                print(GetTime(),instance.id,'is running!')
                break
            sleep(3)
    for instance_id in instance_ids:
        print(GetTime(),'Waiting for instance',instance_id,'to report OK...')
        while 1:
            statuses = ec2.get_all_instance_status([instance_id])
            if len(statuses) < 1:
                sleep(3)
                continue
            status = statuses[0]
            if status.instance_status.status == 'ok':
                print(GetTime(),instance.id,'reported OK!')
                break
            sleep(3)
    for instance in instances:
        machines.append(Machine(instance.ip_address))
    return machines
    
def get_slots(machines):
    slots = []
    #by doing the machines in the inner loop,
    #we end up with heavy jobs split across machines better
    for i in range(0,32):
        for machine in machines:
            slots.append(Slot(machine))
    return slots

