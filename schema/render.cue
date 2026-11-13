package schema

// Flux and Argo CD objects of every cluster, as data: out.<cluster>.{flux,argo}.<file> = object.
// ext_tool.cue writes them to out/<cluster>/{flux,argo}/<file>.yaml.
#Render: {
	clusters: [string]: #Cluster
	apps: [string]:     #App

	out: {
		for cname, c in clusters {
			(cname): {
				flux: #Flux & {#cluster: c, #apps: len(argo) > 0}
				argo: #Argo & {#cluster: c, #apps: [for _, s in apps if s.cluster == cname {s}]}
			}
		}
	}
}

#oidcIssuer: "^https://token\\.actions\\.githubusercontent\\.com$"

// Subject (SAN) of the keyless certificate of the platform-components release workflow. That job is
// defined in platform-components itself (not a reusable workflow), so the SAN names the repository and
// the ref: only reviewed main can publish a set Flux accepts. Flux matches issuer and subject only.
#setSubject: "^https://github\\.com/homelab-selfuryon/platform-components/\\.github/workflows/release\\.yaml@refs/heads/main$"

#labels: {
	"\(#Prefix)/managed-by": "gitops"
	...
}

// Flux objects: a source and a Kustomization per released set, and the Kustomization that applies
// the Argo CD objects once the tenants set is ready.
#Flux: {
	#cluster: #Cluster

	// Whether there are Argo CD objects to apply.
	#apps: bool

	let _released = [for s in #cluster.sets if #cluster.releases[s].digest != _|_ {s}]

	for i, s in _released {
		"ocirepository-set-\(s)": {
			apiVersion: "source.toolkit.fluxcd.io/v1"
			kind:       "OCIRepository"
			metadata: {
				name:      "set-\(s)"
				namespace: "flux-system"
				labels:    #labels & {"\(#Prefix)/component": "set-\(s)"}
			}
			spec: {
				interval: "30m"
				url:      "oci://\(#cluster.componentsRepo)/\(#cluster.name)-\(s)"
				ref: digest: #cluster.releases[s].digest
				layerSelector: {
					mediaType: "application/vnd.oci.image.layer.v1.tar+gzip"
					operation: "extract"
				}
				verify: {
					provider: "cosign"
					matchOIDCIdentity: [{
						issuer:  #oidcIssuer
						subject: #setSubject
					}]
				}
			}
		}
		"kustomization-set-\(s)": {
			apiVersion: "kustomize.toolkit.fluxcd.io/v1"
			kind:       "Kustomization"
			metadata: {
				name:      "set-\(s)"
				namespace: "flux-system"
				labels:    #labels & {"\(#Prefix)/component": "set-\(s)"}
			}
			spec: {
				interval:           "30m"
				timeout:            "15m"
				path:               "./flux"
				prune:              true
				wait:               true
				serviceAccountName: "gitops-root"
				sourceRef:          {kind: "OCIRepository", name: "set-\(s)"}
				if i > 0 {
					dependsOn: [{name: "set-\(_released[i-1])"}]
				}
			}
		}
	}

	if #apps {
		"kustomization-argo-apps": {
			apiVersion: "kustomize.toolkit.fluxcd.io/v1"
			kind:       "Kustomization"
			metadata: {
				name:      "argo-apps"
				namespace: "flux-system"
				labels:    #labels & {"\(#Prefix)/component": "argo-apps"}
			}
			spec: {
				interval:           "10m"
				timeout:            "5m"
				path:               "./argo"
				prune:              true
				wait:               true
				serviceAccountName: "argo-apps"
				sourceRef:          {kind: "OCIRepository", name: "gitops"}
				// Namespaces, AppProjects and deploy ServiceAccounts come with the tenants set.
				dependsOn: [{name: "set-tenants"}]
			}
		}
	}
}

// Argo CD objects of a cluster's apps.
#Argo: {
	#cluster: #Cluster
	#apps:    [...#App]

	for s in #apps {
		let _src = "oci://\(#Registry)/\(s.name)/manifests"
		let _labels = #labels & {
			"\(#Prefix)/team": s.team
		}

		for e in [for env in ["staging", "prod"] if s[env].digest != _|_ {env}] {
			"application-\(s.name)-\(e)": {
				apiVersion: "argoproj.io/v1alpha1"
				kind:       "Application"
				metadata: {
					name: "\(s.name)-\(e)"
					// The team's own namespace (apps in any namespace; its AppProject lists it in
					// sourceNamespaces): the team reads its Applications there and nothing else. The
					// preview ApplicationSet stays in argocd-system (its Applications go where it is).
					namespace: "argocd-\(s.team)"
					labels:    _labels & {"\(#Prefix)/env": e}
				}
				spec: {
					project: s.team
					source: {
						repoURL:        _src
						targetRevision: s[e].digest
						path:           e
					}
					destination: {
						server:    "https://kubernetes.default.svc"
						namespace: "\(s.team)-\(e)"
					}
					syncPolicy: automated: {prune: true, selfHeal: true}
				}
			}
		}

		if s.preview {
			"applicationset-\(s.name)-preview": {
				apiVersion: "argoproj.io/v1alpha1"
				kind:       "ApplicationSet"
				metadata: {
					name:      "\(s.name)-preview"
					namespace: "argocd-system"
					labels:    _labels & {"\(#Prefix)/env": "preview"}
				}
				spec: {
					goTemplate:        true
					goTemplateOptions: ["missingkey=error"]
					generators: [{
						pullRequest: {
							// No token: public repository, 60 requests per hour (see decisions.md, open).
							github: {
								owner: "homelab-selfuryon"
								repo:  s.name
							}
							requeueAfterSeconds: 300
						}
					}]
					template: {
						metadata: {
							name:   "\(s.name)-pr-{{ .number }}"
							labels: _labels & {"\(#Prefix)/env": "preview"}
						}
						spec: {
							project: "\(s.team)-preview"
							source: {
								repoURL:        _src
								targetRevision: "pr-{{ .number }}"
								path:           "preview"
							}
							destination: {
								server:    "https://kubernetes.default.svc"
								namespace: "\(s.team)-pr-{{ .number }}"
							}
							syncPolicy: {
								automated:   {prune: true, selfHeal: true}
								syncOptions: ["CreateNamespace=true"]
								// Pod Security `restricted` like the long-lived namespaces; the platform policy
								// tenant-namespace-labels refuses a tenant namespace without it.
								managedNamespaceMetadata: labels: {
									"\(#Prefix)/team":                    s.team
									"\(#Prefix)/env":                     "preview"
									"pod-security.kubernetes.io/enforce": "restricted"
									"pod-security.kubernetes.io/audit":   "restricted"
									"pod-security.kubernetes.io/warn":    "restricted"
								}
							}
						}
					}
				}
			}
		}
	}
}
