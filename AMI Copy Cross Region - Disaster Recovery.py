# This script copies the AMI to other region and add tag 'DeleteOnCopy' with retention days specified.
import boto3
from dateutil import parser
import datetime
import collections

# Set the global variables
globalVars  = dict()
globalVars['Owner']                 = 'Disaster Recovery'
globalVars['Environment']           = 'Disaster Recovery'
globalVars['SourceRegion']          = 'ap-southeast-2'
globalVars['destRegions']           = ['us-west-2']        # List of AWS Regions to which the AMI to be copied
globalVars['amiRetentionDays']      = int(180)                # AMI Rentention days in DR/Destination Region.

# Create the Boto Resources and Clients
srcEC2Resource = boto3.resource('ec2', region_name = globalVars['SourceRegion'])

# Get the Account ID of the Lambda Runner Account - Assuming this is the source account
globalVars['awsAccountId'] = boto3.client('sts').get_caller_identity()['Account']

def img_replicator():
# Get the list of images in source Region that were not created by DR solution CloudRanger
# Boto3 does not support 'does not equal', so I need to do a remove from list
# Get all self made AMIs
    instances_all = [i for i in boto3.resource('ec2', region_name='ap-southeast-2').images.filter(Owners=['self'])]
    # Get all CloudRanger AMIs
    instances_cloudranger = [i for i in boto3.resource('ec2', region_name='ap-southeast-2').images.filter(Owners=['self'], Filters=[{'Name':'description', 'Values':['*CloudRanger*']}])]
    # Create list of non CloudRanger AMIs (instances_all minus instances_cloudranger)
    images = [instance_to_copy for instance_to_copy in instances_all if instance_to_copy.id not in [i.id for i in instances_cloudranger]]
    # for instance in instances_to_copy:
    #	print(instance.id)

    to_tag = collections.defaultdict(list)

    imgReplicationStatus = {'Images': []}

    for image in images:
        image_date = parser.parse(image.creation_date)

        # To Copy previous day images
        if image_date.date() > (datetime.datetime.today()-datetime.timedelta(40)).date():
            print("New Images: Image Name:{name} ID:{id} DATE:{date}'".format(name=image.name,id=image.id,date=image.creation_date))
            # Copy to Multiple destinations
            for awsRegion in globalVars['destRegions']:

                destEC2Client = boto3.client('ec2', region_name=awsRegion)
                # Copy ONLY if the destination doesn't have an image already with the same name
                # AMI Names have to be UNIQUE
                if not destEC2Client.describe_images(Owners=[ globalVars['awsAccountId'] ], Filters=[{'Name':'name', 'Values':[image.name]}])['Images']:
                #if 1 == 1:
                    print("Copying Image. Image Name:{name} ; ID:{id} ; Region:'{dest}'".format(name=image.name,id=image.id, dest=awsRegion))

                    # Prevent Error caused null description value
                    try:
                        descriptionval=image.description
                    except:
                        descriptionval=image.name
                    else:
                        descriptionval=image.name
                    

                    new_ami = destEC2Client.copy_image(
                        DryRun=False,
                        SourceRegion=globalVars['SourceRegion'],
                        SourceImageId=image.id,
                        Name=image.name,
                        Description=descriptionval
                    )

                    to_tag[ globalVars['amiRetentionDays'] ].append(new_ami['ImageId'])

                    imgReplicationStatus['Images'].append({'Source-Image-Id':image.id,
                                                           'Destination-Image-Id':new_ami['ImageId'],
                                                           'RetentionDays':globalVars['amiRetentionDays'],
                                                           'Status':'Copied'})

                    for ami_retention_days in to_tag.keys():
                        delete_date = datetime.date.today() + datetime.timedelta(days=globalVars['amiRetentionDays'])
                        delete_fmt = delete_date.strftime('%d-%m-%Y')
                        #print ("Will delete {0} AMIs on {1}".format(len(to_tag[globalVars['amiRetentionDays']]), delete_fmt))


                        #Get Tags from Original AMI, add new Tags to the list
                        amitags = image.tags
                        # print(amitags)
                        newtags = [
                                    {'Key': 'DeleteOnCopy', 'Value': delete_fmt},
                                    {'Key': 'RetainUntil', 'Value': delete_fmt},
                                    {'Key': 'CreatedBy', 'Value': 'Disaster Recovery AMI Replicator Lambda'},
                                    {'Key': 'OriginRegion', 'Value': 'ap-southeast-2 (Sydney)'},
                                    {'Key': 'OriginAMIid', 'Value': image.id},
                                    {'Key': 'OriginCreationDate', 'Value': image.creation_date}
                                ]
                        # print(newtags)
                        
                        amitags = amitags + newtags 
                        print(amitags)
        

                        # Add tag to the AMI enabling Lambda to delete/cleanUp after retention period expires
                        destEC2Client.create_tags( Resources=to_tag[globalVars['amiRetentionDays']],
                                                   Tags = amitags
                                                 )
                else:
                    print("Image {name} - {id} already present in Oregon Region".format( name=image.name, id=image.id ))
                    imgReplicationStatus['Images'].append({'AMI-Id':image.id,'Status':'Already Exists'})


        # else:
            # print("There are no new images. The Image: {name} with AMI ID: {id} was created on {date}".format(name=image.name, id=image.id, date=image_date.strftime('%d-%m-%Y')))

    return imgReplicationStatus


def lambda_handler(event, context):
    img_replicator()

if __name__ == '__main__':
    lambda_handler(None, None)