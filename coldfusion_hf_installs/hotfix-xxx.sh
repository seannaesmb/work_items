#/bin/bash -x

# Set the expected username
EXPECTED_USER="tomcat"

# Get the current username
CURRENT_USER=$(whoami)

# Compare and exit if not the expected user
if [[ "$CURRENT_USER" != "$EXPECTED_USER" ]]; then
    echo "Error: This script must be run as user '$EXPECTED_USER'. Current user is '$CURRENT_USER'."
    exit 1
fi

# Archive contents for /opt/coldfusion2021

#tar -czpf coldfusion2021_$(date +%Y%m%d)_prior_hf_upgrade.tar.gz /opt/coldfusion2021/ROOT

if [[ "$?" != "0" ]]; then
    echo "Archive threw error please check"
    exit 1
fi

# Continue with the rest of the script
echo "Running as the correct user: $CURRENT_USER"

cd /opt/inst/coldfusion/2023/

mkdir -p /opt/inst/coldfusion/2023/hotfix-018-330879.tmp

TMP=/opt/inst/coldfusion/2023/hotfix-018-330879.tmp
TEMP=/opt/inst/coldfusion/2023/hotfix-018-330879.tmp

#if [[ "$(sha256sum hotfix-018-330879.jar| awk '{print $1}')" == "$(echo CBBC0C98DE760D7FFBAAB9E3A8537194EFC3DD50B894B09647EBE1C755D6112B|  tr [:upper:] [:lower:])" ]]; then
    java -Djdk.util.zip.disableZip64ExtraFieldValidation=true -jar /opt/inst/coldfusion/2023/hotfix-018-330879.jar -f /opt/inst/coldfusion/2023/hotfix-018.properties
#fi


echo -e "Please add -Dcoldfusion.runtime.remotemethod.matchArguments=false to argument in /etc/tomcat/conf/tomcat.conf \n"

echo -e "Please note -Dcoldfusion.systemprobe.allowexecution=true/false as set to FALSE by default \n"

echo -e "Please check lockdown as noted here: \n If you want to apply lockdown on this update, add the -Dcoldfusion.runtime.remotemethod.matchArguments flag"

echo -e "serialfilter.txt replaced please validate file \n cfusion/hf-updates/{version}/backup/lib and different noted"

echo -e "STOP app server & remove /bin/felix-cache folder.  Then start back up"
##
#Algorithm       Hash                                                                   Path
#---------       ----                                                                   ----
#SHA256          CBBC0C98DE760D7FFBAAB9E3A8537194EFC3DD50B894B09647EBE1C755D6112B       C:\Users\1403969881.CTR\Downloa…
