"""Network exposure scanner, VPC, security groups, public access."""

from .base import BaseScanner, ScanResult, Severity
from ..utils.aws import safe_api_call, parallel_collect

DANGEROUS_PORTS = {
    22: "SSH", 23: "Telnet", 25: "SMTP", 1433: "MSSQL", 1521: "Oracle",
    2222: "SSH-Alt", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 5985: "WinRM", 5986: "WinRM-SSL", 6379: "Redis",
    9200: "Elasticsearch", 11211: "Memcached", 27017: "MongoDB",
}
MGMT_PORTS = {22, 3389, 5985, 5986}
DB_PORTS = {3306, 5432, 1433, 1521, 27017, 6379, 9200, 11211}


class NetworkScanner(BaseScanner):
    category = "Network Exposure"

    def scan(self) -> ScanResult:
        all_sgs = []
        all_vpcs = []
        all_subnets = []
        all_igws = []
        all_flow_logs = []

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            sgs, _ = safe_api_call(ec2, "describe_security_groups")
            for sg in (sgs or {}).get("SecurityGroups", []):
                sg["_region"] = region
                all_sgs.append(sg)

            vpcs, _ = safe_api_call(ec2, "describe_vpcs")
            for vpc in (vpcs or {}).get("Vpcs", []):
                vpc["_region"] = region
                all_vpcs.append(vpc)

            subnets, _ = safe_api_call(ec2, "describe_subnets")
            for sn in (subnets or {}).get("Subnets", []):
                sn["_region"] = region
                all_subnets.append(sn)

            igws, _ = safe_api_call(ec2, "describe_internet_gateways")
            for igw in (igws or {}).get("InternetGateways", []):
                igw["_region"] = region
                all_igws.append(igw)

            fls, _ = safe_api_call(ec2, "describe_flow_logs")
            for fl in (fls or {}).get("FlowLogs", []):
                fl["_region"] = region
                all_flow_logs.append(fl)

            peerings, _ = safe_api_call(ec2, "describe_vpc_peering_connections")
            for p in (peerings or {}).get("VpcPeeringConnections", []):
                p["_region"] = region

            self.advance()

        self.resources = {
            "security_groups": all_sgs, "vpcs": all_vpcs,
            "subnets": all_subnets, "internet_gateways": all_igws,
            "flow_logs": all_flow_logs,
        }

        self._check_open_security_groups(all_sgs)
        self._check_management_ports(all_sgs)
        self._check_database_ports(all_sgs)
        self._check_default_vpc(all_vpcs)
        self._check_flow_logs(all_vpcs, all_flow_logs)
        self._check_public_subnets(all_subnets)

        # Checks merged from awsnet, network hygiene
        self._check_blackhole_routes()
        self._check_vpc_endpoints(all_vpcs)
        self._check_wide_open_nacls()
        self._check_vpn_tunnels()

        return ScanResult(findings=self.findings, resources=self.resources, errors=self.errors)

    def _check_open_security_groups(self, sgs):
        for sg in sgs:
            for rule in sg.get("IpPermissions", []):
                for ip_range in rule.get("IpRanges", []):
                    if ip_range.get("CidrIp") == "0.0.0.0/0":
                        from_port = rule.get("FromPort", 0)
                        to_port = rule.get("ToPort", 65535)
                        if from_port == 0 and to_port == 65535:
                            self.add_finding(
                                check_id="NET-001",
                                title=f"SG '{sg['GroupId']}' allows ALL ports from internet",
                                severity=Severity.CRITICAL, resource_type="AWS::EC2::SecurityGroup",
                                resource_id=sg["GroupId"], region=sg["_region"],
                                description=f"Security group {sg.get('GroupName', '')} in VPC {sg.get('VpcId', '')} allows all traffic from 0.0.0.0/0.",
                                remediation="Restrict inbound rules to specific ports and source IPs.")

    def _check_management_ports(self, sgs):
        for sg in sgs:
            for rule in sg.get("IpPermissions", []):
                for ip_range in rule.get("IpRanges", []) + rule.get("Ipv6Ranges", []):
                    cidr = ip_range.get("CidrIp", ip_range.get("CidrIpv6", ""))
                    if cidr in ("0.0.0.0/0", "::/0"):
                        from_port = rule.get("FromPort", 0)
                        to_port = rule.get("ToPort", 0)
                        for port in MGMT_PORTS:
                            if from_port <= port <= to_port:
                                self.add_finding(
                                    check_id="NET-002",
                                    title=f"SG '{sg['GroupId']}' exposes {DANGEROUS_PORTS.get(port, port)} to internet",
                                    severity=Severity.CRITICAL, resource_type="AWS::EC2::SecurityGroup",
                                    resource_id=sg["GroupId"], region=sg["_region"],
                                    description=f"Port {port} ({DANGEROUS_PORTS.get(port, 'unknown')}) is open to {cidr}.",
                                    remediation=f"Restrict port {port} to specific trusted IPs or use SSM Session Manager.")

    def _check_database_ports(self, sgs):
        for sg in sgs:
            for rule in sg.get("IpPermissions", []):
                for ip_range in rule.get("IpRanges", []) + rule.get("Ipv6Ranges", []):
                    cidr = ip_range.get("CidrIp", ip_range.get("CidrIpv6", ""))
                    if cidr in ("0.0.0.0/0", "::/0"):
                        from_port = rule.get("FromPort", 0)
                        to_port = rule.get("ToPort", 0)
                        for port in DB_PORTS:
                            if from_port <= port <= to_port:
                                self.add_finding(
                                    check_id="NET-003",
                                    title=f"SG '{sg['GroupId']}' exposes {DANGEROUS_PORTS.get(port, port)} to internet",
                                    severity=Severity.CRITICAL, resource_type="AWS::EC2::SecurityGroup",
                                    resource_id=sg["GroupId"], region=sg["_region"],
                                    description=f"Database port {port} ({DANGEROUS_PORTS.get(port, 'unknown')}) open to internet.",
                                    remediation=f"Never expose database ports to the internet. Use private subnets and VPN/bastion.")

    def _check_default_vpc(self, vpcs):
        for vpc in vpcs:
            if vpc.get("IsDefault"):
                self.add_finding(
                    check_id="NET-004", title=f"Default VPC in use in {vpc['_region']}",
                    severity=Severity.MEDIUM, resource_type="AWS::EC2::VPC",
                    resource_id=vpc["VpcId"], region=vpc["_region"],
                    description="Default VPC provides less control over network segmentation.",
                    remediation="Create custom VPCs with proper subnet design and remove default VPC.")

    def _check_flow_logs(self, vpcs, flow_logs):
        vpc_ids_with_logs = {fl["ResourceId"] for fl in flow_logs if fl.get("ResourceId")}
        for vpc in vpcs:
            if vpc["VpcId"] not in vpc_ids_with_logs:
                self.add_finding(
                    check_id="NET-005", title=f"VPC '{vpc['VpcId']}' has no flow logs",
                    severity=Severity.HIGH, resource_type="AWS::EC2::VPC",
                    resource_id=vpc["VpcId"], region=vpc["_region"],
                    description="No VPC flow logs means no visibility into network traffic.",
                    remediation="Enable VPC flow logs to CloudWatch Logs or S3.")

    def _check_public_subnets(self, subnets):
        for sn in subnets:
            if sn.get("MapPublicIpOnLaunch"):
                self.add_finding(
                    check_id="NET-006", title=f"Subnet '{sn['SubnetId']}' auto-assigns public IPs",
                    severity=Severity.HIGH, resource_type="AWS::EC2::Subnet",
                    resource_id=sn["SubnetId"], region=sn["_region"],
                    description="Instances launched here automatically get public IPs.",
                    remediation="Disable auto-assign public IP unless explicitly needed.")


    # ── Checks merged from awsnet ─────────────────────────────────────────

    def _check_blackhole_routes(self):
        """Detect blackhole routes pointing to deleted resources."""
        blackhole_count = 0
        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            rt_resp, err = safe_api_call(ec2, "describe_route_tables")
            if err:
                self.errors.append(f"Route tables ({region}): {err}")
                continue
            for rt in (rt_resp or {}).get("RouteTables", []):
                for route in rt.get("Routes", []):
                    if route.get("State") == "blackhole":
                        blackhole_count += 1
        if blackhole_count > 0:
            self.add_finding(
                check_id="NET-007",
                title=f"{blackhole_count} blackhole route(s) detected",
                severity=Severity.MEDIUM, resource_type="AWS::EC2::RouteTable",
                resource_id="blackhole-routes",
                description="Routes pointing to deleted resources (NAT GW, peering, etc.).",
                remediation="Clean up stale routes or recreate the target resources.")

    def _check_vpc_endpoints(self, vpcs):
        """Check if VPC endpoints exist for S3/DynamoDB (cost + security)."""
        total_endpoints = 0
        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            ep_resp, _ = safe_api_call(ec2, "describe_vpc_endpoints")
            total_endpoints += len((ep_resp or {}).get("VpcEndpoints", []))
        if total_endpoints == 0 and len(vpcs) > 0:
            self.add_finding(
                check_id="NET-008",
                title="No VPC endpoints configured",
                severity=Severity.MEDIUM, resource_type="AWS::EC2::VPCEndpoint",
                resource_id="no-vpc-endpoints",
                description="All S3/DynamoDB traffic goes via IGW (higher cost, less secure).",
                remediation="Add gateway endpoints for S3 and DynamoDB in each VPC.")

    def _check_wide_open_nacls(self):
        """Detect NACLs that allow all inbound traffic from 0.0.0.0/0."""
        wide_open = 0
        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            nacl_resp, _ = safe_api_call(ec2, "describe_network_acls")
            for nacl in (nacl_resp or {}).get("NetworkAcls", []):
                if nacl.get("IsDefault"):
                    continue
                for entry in nacl.get("Entries", []):
                    if (not entry.get("Egress") and entry.get("RuleAction") == "allow"
                            and entry.get("CidrBlock") == "0.0.0.0/0"
                            and entry.get("Protocol") == "-1"
                            and entry.get("RuleNumber", 0) < 32767):
                        wide_open += 1
                        break
        if wide_open > 0:
            self.add_finding(
                check_id="NET-009",
                title=f"{wide_open} custom NACL(s) allow ALL inbound from 0.0.0.0/0",
                severity=Severity.HIGH, resource_type="AWS::EC2::NetworkAcl",
                resource_id="wide-open-nacls",
                description="Custom NACLs with allow-all inbound bypass security group restrictions.",
                remediation="Restrict NACL inbound rules to specific ports and CIDR ranges.")

    def _check_vpn_tunnels(self):
        """Detect VPN tunnels in DOWN state."""
        tunnels_down = 0
        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            try:
                vpn_resp, _ = safe_api_call(ec2, "describe_vpn_connections",
                                             Filters=[{"Name": "state", "Values": ["available"]}])
                for vpn in (vpn_resp or {}).get("VpnConnections", []):
                    for tun in vpn.get("VgwTelemetry", []):
                        if tun.get("Status") == "DOWN":
                            tunnels_down += 1
            except Exception:
                pass
        if tunnels_down > 0:
            self.add_finding(
                check_id="NET-010",
                title=f"{tunnels_down} VPN tunnel(s) in DOWN state",
                severity=Severity.HIGH, resource_type="AWS::EC2::VPNConnection",
                resource_id="vpn-tunnels-down",
                description="VPN connectivity is degraded. Hybrid workloads may be affected.",
                remediation="Investigate and restore VPN tunnels. Check CGW configuration.")
